"""Tenant-safe persistence for the v6 parallel parsing control plane.

The v6 runtime never mutates a provider result into a retry.  Each provider
invocation is an immutable ``parse_attempts`` row, each validation is
append-only evidence, and only one accepted block may own a logical output.
This module intentionally remains separate from the legacy page-attempt state
machine so rollout can run in shadow mode without weakening production gates.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from akc_api.database import Base
from akc_api.models import utcnow, uuid4


class ParallelParseShard(Base):
    """A deterministic, context-carrying unit of parallel parse work."""

    __tablename__ = "parse_shards"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    processing_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    document_version_id: Mapped[str] = mapped_column(String(160), nullable=False)
    parent_shard_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    shard_key: Mapped[str] = mapped_column(String(160), nullable=False)
    shard_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    region: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    overlap: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    ownership: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    route_class: Mapped[str] = mapped_column(String(80), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    size_units: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    plan_version: Mapped[str] = mapped_column(String(120), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PLANNED", nullable=False)
    dispatch_idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "collection_id"],
            ["collections.tenant_id", "collections.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "processing_job_id"],
            ["processing_jobs.tenant_id", "processing_jobs.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_shard_id"],
            ["parse_shards.tenant_id", "parse_shards.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "processing_job_id",
            "document_version_id",
            "shard_key",
            "plan_version",
            name="uq_parse_shards_generation_key",
        ),
        UniqueConstraint("tenant_id", "dispatch_idempotency_key"),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "processing_job_id",
            "document_version_id",
            "id",
            name="uq_parse_shards_acceptance_scope",
        ),
        CheckConstraint(
            "shard_kind IN ("
            "'collection','document','section','page_group','page',"
            "'region','table','row','cell')",
            name="ck_parse_shards_kind",
        ),
        CheckConstraint("ordinal >= 0", name="ck_parse_shards_ordinal"),
        CheckConstraint(
            "page_start >= 1 AND page_end >= page_start",
            name="ck_parse_shards_page_range",
        ),
        CheckConstraint("priority BETWEEN 0 AND 100", name="ck_parse_shards_priority"),
        CheckConstraint("size_units >= 1", name="ck_parse_shards_size_units"),
        CheckConstraint("length(input_sha256) = 64", name="ck_parse_shards_input_sha"),
        CheckConstraint(
            "status IN ("
            "'PLANNED','QUEUED','DISPATCHED','RUNNING','VALIDATING','ACCEPTED',"
            "'RECOVERY_PENDING','UNRESOLVED','QUARANTINED','FAILED','SUPERSEDED')",
            name="ck_parse_shards_status",
        ),
        Index(
            "parse_shards_document_queue_idx",
            "tenant_id",
            "document_id",
            "status",
            "priority",
            "ordinal",
        ),
        Index(
            "parse_shards_job_idx",
            "tenant_id",
            "processing_job_id",
            "document_version_id",
            "status",
        ),
    )


class ParallelParseAttempt(Base):
    """One immutable provider output and its bounded lifecycle state."""

    __tablename__ = "parse_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    shard_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    parent_attempt_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    provider_invocation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="CREATED", nullable=False)
    pool_key: Mapped[str] = mapped_column(String(120), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(160))
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(160), nullable=False)
    runtime_identity: Mapped[str] = mapped_column(String(160), nullable=False)
    route_policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_artifact_key: Mapped[str | None] = mapped_column(String(500))
    output_sha256: Mapped[str | None] = mapped_column(String(64))
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    failure_domain: Mapped[str | None] = mapped_column(String(24))
    failure_code: Mapped[str | None] = mapped_column(String(120))
    billing_disposition: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    gpu_milliseconds: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    output_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "shard_id"],
            ["parse_shards.tenant_id", "parse_shards.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_attempt_id"],
            ["parse_attempts.tenant_id", "parse_attempts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "provider_invocation_id"],
            ["gpu_provider_invocations.tenant_id", "gpu_provider_invocations.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(
            "tenant_id",
            "shard_id",
            "id",
            name="uq_parse_attempts_shard_scope",
        ),
        UniqueConstraint("shard_id", "attempt_number"),
        UniqueConstraint("tenant_id", "idempotency_key"),
        UniqueConstraint("provider_invocation_id"),
        CheckConstraint("attempt_number >= 1", name="ck_parse_attempts_number"),
        CheckConstraint(
            "attempt_kind IN ('primary','retry','hedge','straggler','recovery','shadow')",
            name="ck_parse_attempts_kind",
        ),
        CheckConstraint(
            "state IN ("
            "'CREATED','QUEUED','RUNNING','OUTPUT_RECEIVED','VALIDATING','ACCEPTED',"
            "'REJECTED','RETRYABLE_FAILED','TERMINAL_FAILED','SUPERSEDED','QUARANTINED')",
            name="ck_parse_attempts_state",
        ),
        CheckConstraint(
            "failure_domain IS NULL OR failure_domain IN ("
            "'infrastructure','semantic','policy','cancelled')",
            name="ck_parse_attempts_failure_domain",
        ),
        CheckConstraint(
            "billing_disposition IN ("
            "'pending','accepted_billable','retry_unbillable','speculative_unbillable',"
            "'straggler_unbillable','unresolved_unbillable','quarantine_unbillable',"
            "'refunded','shadow_unbillable')",
            name="ck_parse_attempts_billing",
        ),
        CheckConstraint("gpu_milliseconds >= 0", name="ck_parse_attempts_gpu_ms"),
        CheckConstraint("cost_usd >= 0", name="ck_parse_attempts_cost"),
        CheckConstraint("length(request_sha256) = 64", name="ck_parse_attempts_request_sha"),
        CheckConstraint(
            "output_sha256 IS NULL OR length(output_sha256) = 64",
            name="ck_parse_attempts_output_sha",
        ),
        CheckConstraint(
            "(output_artifact_key IS NULL AND output_sha256 IS NULL "
            "AND output_received_at IS NULL) OR "
            "(output_artifact_key IS NOT NULL AND output_sha256 IS NOT NULL "
            "AND output_received_at IS NOT NULL)",
            name="ck_parse_attempts_output_shape",
        ),
        Index("parse_attempts_shard_state_idx", "shard_id", "state", "attempt_number"),
        Index("parse_attempts_worker_idx", "tenant_id", "worker_id", "created_at"),
    )


class AttemptValidation(Base):
    """Append-only validator evidence for a parse attempt."""

    __tablename__ = "attempt_validations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    validator_key: Mapped[str] = mapped_column(String(120), nullable=False)
    validator_revision: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(9, 8))
    hard_fail: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "attempt_id"],
            ["parse_attempts.tenant_id", "parse_attempts.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("attempt_id", "level", "validator_key", "validator_revision"),
        CheckConstraint("level BETWEEN 0 AND 6", name="ck_attempt_validations_level"),
        CheckConstraint(
            "status IN ('passed','failed','abstained','unavailable')",
            name="ck_attempt_validations_status",
        ),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)",
            name="ck_attempt_validations_score",
        ),
        CheckConstraint("length(evidence_sha256) = 64", name="ck_attempt_validations_evidence_sha"),
        Index("attempt_validations_attempt_idx", "attempt_id", "level", "status"),
    )


class WorkerHealth(Base):
    """Current infrastructure and semantic health projection for one worker."""

    __tablename__ = "worker_health"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(160), nullable=False)
    pool_key: Mapped[str] = mapped_column(String(120), nullable=False)
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    runtime_identity: Mapped[str] = mapped_column(String(160), nullable=False)
    region: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    infrastructure_status: Mapped[str] = mapped_column(String(24), nullable=False)
    semantic_status: Mapped[str] = mapped_column(String(24), nullable=False)
    infrastructure_score: Mapped[Decimal] = mapped_column(Numeric(9, 8), nullable=False)
    semantic_score: Mapped[Decimal] = mapped_column(Numeric(9, 8), nullable=False)
    inflight: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    consecutive_semantic_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    drain_reason: Mapped[str | None] = mapped_column(String(120))
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_canary_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "worker_id"),
        CheckConstraint(
            "state IN ('HEALTHY','DEGRADED','DRAINING','QUARANTINED','TERMINATED')",
            name="ck_worker_health_state",
        ),
        CheckConstraint(
            "infrastructure_status IN ('healthy','degraded','unreachable','terminated')",
            name="ck_worker_health_infra_status",
        ),
        CheckConstraint(
            "semantic_status IN ('healthy','degraded','failing','unknown')",
            name="ck_worker_health_semantic_status",
        ),
        CheckConstraint(
            "infrastructure_score >= 0 AND infrastructure_score <= 1",
            name="ck_worker_health_infra_score",
        ),
        CheckConstraint(
            "semantic_score >= 0 AND semantic_score <= 1",
            name="ck_worker_health_semantic_score",
        ),
        CheckConstraint("inflight >= 0", name="ck_worker_health_inflight"),
        CheckConstraint("capacity >= 1", name="ck_worker_health_capacity"),
        CheckConstraint(
            "inflight <= capacity",
            name="ck_worker_health_inflight_capacity",
        ),
        CheckConstraint(
            "consecutive_semantic_failures >= 0",
            name="ck_worker_health_semantic_failures",
        ),
        Index("worker_health_pool_idx", "tenant_id", "pool_key", "state", "inflight"),
    )


class SemanticHealthEvent(Base):
    """Append-only semantic canary or impact-analysis observation."""

    __tablename__ = "semantic_health_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    worker_health_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    previous_state: Mapped[str] = mapped_column(String(24), nullable=False)
    current_state: Mapped[str] = mapped_column(String(24), nullable=False)
    semantic_score: Mapped[Decimal] = mapped_column(Numeric(9, 8), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    impacted_attempt_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "worker_health_id"],
            ["worker_health.tenant_id", "worker_health.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint(
            "event_type IN ("
            "'canary_passed','canary_failed','degraded','draining',"
            "'quarantined','recovered','impact_replay_requested')",
            name="ck_semantic_health_events_type",
        ),
        CheckConstraint(
            "previous_state IN ('HEALTHY','DEGRADED','DRAINING','QUARANTINED','TERMINATED')",
            name="ck_semantic_health_events_previous",
        ),
        CheckConstraint(
            "current_state IN ('HEALTHY','DEGRADED','DRAINING','QUARANTINED','TERMINATED')",
            name="ck_semantic_health_events_current",
        ),
        CheckConstraint(
            "semantic_score >= 0 AND semantic_score <= 1",
            name="ck_semantic_health_events_score",
        ),
        CheckConstraint(
            "length(evidence_sha256) = 64", name="ck_semantic_health_events_evidence_sha"
        ),
        Index(
            "semantic_health_events_worker_idx",
            "worker_health_id",
            "occurred_at",
        ),
    )


class ContinuityEdge(Base):
    """Evidence-bound edge used by deterministic document continuity merge."""

    __tablename__ = "continuity_edges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_shard_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    target_shard_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    edge_type: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(9, 8), nullable=False)
    authority: Mapped[str] = mapped_column(String(24), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    merge_revision: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="candidate", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_shard_id"],
            ["parse_shards.tenant_id", "parse_shards.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "target_shard_id"],
            ["parse_shards.tenant_id", "parse_shards.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(
            "document_id",
            "source_shard_id",
            "target_shard_id",
            "edge_type",
            "merge_revision",
        ),
        CheckConstraint("source_shard_id <> target_shard_id", name="ck_continuity_edges_distinct"),
        CheckConstraint(
            "edge_type IN ("
            "'heading_continuation','paragraph_continuation','list_continuation',"
            "'table_continuation','figure_caption','footnote_reference',"
            "'reading_order','overlap_equivalence')",
            name="ck_continuity_edges_type",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_continuity_edges_confidence"
        ),
        CheckConstraint(
            "authority IN ('deterministic','native','authority','cross_model','multimodal')",
            name="ck_continuity_edges_authority",
        ),
        CheckConstraint(
            "status IN ('candidate','accepted','rejected','unresolved')",
            name="ck_continuity_edges_status",
        ),
        CheckConstraint("length(evidence_sha256) = 64", name="ck_continuity_edges_evidence_sha"),
        Index("continuity_edges_document_idx", "document_id", "status", "edge_type"),
    )


class AcceptedBlock(Base):
    """Single-winner projection with exactly-once credit ownership."""

    __tablename__ = "accepted_blocks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    processing_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    document_version_id: Mapped[str] = mapped_column(String(160), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    shard_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    arbitration_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    logical_block_key: Mapped[str] = mapped_column(String(200), nullable=False)
    final_state: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_key: Mapped[str] = mapped_column(String(500), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    acceptance_idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    credit_settlement_key: Mapped[str | None] = mapped_column(String(160))
    billable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    credit_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=Decimal("0"), nullable=False
    )
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "processing_job_id"],
            ["processing_jobs.tenant_id", "processing_jobs.id"],
            name="fk_accepted_blocks_processing_job_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "document_id",
                "processing_job_id",
                "document_version_id",
                "shard_id",
            ],
            [
                "parse_shards.tenant_id",
                "parse_shards.document_id",
                "parse_shards.processing_job_id",
                "parse_shards.document_version_id",
                "parse_shards.id",
            ],
            name="fk_accepted_blocks_shard_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "shard_id", "attempt_id"],
            ["parse_attempts.tenant_id", "parse_attempts.shard_id", "parse_attempts.id"],
            name="fk_accepted_blocks_attempt_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "arbitration_id"],
            ["arbitration_decisions.tenant_id", "arbitration_decisions.id"],
            name="fk_accepted_blocks_arbitration",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(
            "tenant_id",
            "arbitration_id",
            name="uq_accepted_blocks_arbitration",
        ),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "processing_job_id",
            "document_version_id",
            "logical_block_key",
            "generation",
            name="uq_accepted_blocks_generation_key",
        ),
        UniqueConstraint("attempt_id", "logical_block_key"),
        UniqueConstraint("tenant_id", "acceptance_idempotency_key"),
        UniqueConstraint("tenant_id", "credit_settlement_key"),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "processing_job_id",
            "document_version_id",
            "generation",
            "shard_id",
            "attempt_id",
            "id",
            name="uq_accepted_blocks_invalidation_scope",
        ),
        CheckConstraint(
            "final_state IN ("
            "'verified','authority_verified','cross_model_verified','auto_repaired',"
            "'unresolved','quarantined','failed')",
            name="ck_accepted_blocks_state",
        ),
        CheckConstraint("length(artifact_sha256) = 64", name="ck_accepted_blocks_artifact_sha"),
        CheckConstraint("generation >= 1", name="ck_accepted_blocks_generation"),
        CheckConstraint("credit_amount >= 0", name="ck_accepted_blocks_credit"),
        CheckConstraint(
            "(billable AND final_state IN ("
            "'verified','authority_verified','cross_model_verified','auto_repaired') "
            "AND credit_settlement_key IS NOT NULL AND credit_amount > 0) OR "
            "(NOT billable AND credit_settlement_key IS NULL AND credit_amount = 0)",
            name="ck_accepted_blocks_billing_shape",
        ),
        Index(
            "accepted_blocks_document_idx",
            "tenant_id",
            "document_id",
            "processing_job_id",
            "document_version_id",
            "generation",
            "final_state",
            "accepted_at",
        ),
    )


class AcceptedBlockInvalidation(Base):
    """Append-only evidence that revokes one immutable accepted-block generation."""

    __tablename__ = "accepted_block_invalidations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    processing_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    document_version_id: Mapped[str] = mapped_column(String(160), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    shard_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    accepted_block_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    recovery_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(120), nullable=False)
    operation_key: Mapped[str] = mapped_column(String(200), nullable=False)
    operation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    refund_settlement_key: Mapped[str | None] = mapped_column(String(200))
    refund_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=Decimal("0"), nullable=False
    )
    refund_ledger_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    invalidated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
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
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "accepted_block_id"),
        UniqueConstraint("tenant_id", "operation_key"),
        UniqueConstraint("tenant_id", "operation_sha256"),
        UniqueConstraint("tenant_id", "refund_settlement_key"),
        CheckConstraint(
            "action IN ('invalidated','revoked')",
            name="ck_accepted_block_invalidations_action",
        ),
        CheckConstraint(
            "length(reason_code) BETWEEN 1 AND 120",
            name="ck_accepted_block_invalidations_reason",
        ),
        CheckConstraint(
            "length(operation_sha256) = 64",
            name="ck_accepted_block_invalidations_operation_sha",
        ),
        CheckConstraint(
            "length(evidence_sha256) = 64",
            name="ck_accepted_block_invalidations_evidence_sha",
        ),
        CheckConstraint(
            "generation >= 1",
            name="ck_accepted_block_invalidations_generation",
        ),
        CheckConstraint(
            "(refund_ledger_id IS NULL AND refund_settlement_key IS NULL "
            "AND refund_amount = 0) OR "
            "(refund_ledger_id IS NOT NULL AND refund_settlement_key IS NOT NULL "
            "AND refund_amount > 0)",
            name="ck_accepted_block_invalidations_refund_shape",
        ),
        Index(
            "accepted_block_invalidations_active_lookup_idx",
            "tenant_id",
            "document_id",
            "processing_job_id",
            "document_version_id",
            "generation",
            "accepted_block_id",
        ),
        Index(
            "accepted_block_invalidations_recovery_idx",
            "tenant_id",
            "recovery_task_id",
        ),
    )


class RecoveryTask(Base):
    """Selective cell-to-page recovery request; retries create new attempts."""

    __tablename__ = "recovery_tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    shard_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    recovery_level: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(120), nullable=False)
    target: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    preprocessing_variants: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    route_candidates: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    state: Mapped[str] = mapped_column(String(24), default="REQUESTED", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    result_attempt_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "shard_id"],
            ["parse_shards.tenant_id", "parse_shards.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_attempt_id"],
            ["parse_attempts.tenant_id", "parse_attempts.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "result_attempt_id"],
            ["parse_attempts.tenant_id", "parse_attempts.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "idempotency_key"),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "shard_id",
            "id",
            name="uq_recovery_tasks_invalidation_scope",
        ),
        CheckConstraint(
            "recovery_level IN ('cell','row','table','region','page','page_group')",
            name="ck_recovery_tasks_level",
        ),
        CheckConstraint(
            "state IN ("
            "'REQUESTED','QUEUED','RUNNING','VALIDATING','COMPLETED',"
            "'UNRESOLVED','FAILED','CANCELLED')",
            name="ck_recovery_tasks_state",
        ),
        CheckConstraint(
            "(state = 'COMPLETED' AND result_attempt_id IS NOT NULL "
            "AND completed_at IS NOT NULL) OR "
            "(state IN ('UNRESOLVED','FAILED','CANCELLED') AND completed_at IS NOT NULL) OR "
            "(state IN ('REQUESTED','QUEUED','RUNNING','VALIDATING') "
            "AND result_attempt_id IS NULL AND completed_at IS NULL)",
            name="ck_recovery_tasks_terminal",
        ),
        Index("recovery_tasks_document_idx", "document_id", "state", "created_at"),
    )


class ArbitrationDecision(Base):
    """Authority-prioritized resolution; majority alone is never sufficient."""

    __tablename__ = "arbitration_decisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    shard_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    decision_key: Mapped[str] = mapped_column(String(160), nullable=False)
    logical_unit_key: Mapped[str] = mapped_column(String(200), nullable=False)
    logical_unit_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_attempt_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    excluded_attempt_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    selected_attempt_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    authority_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    priced_credit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "shard_id"],
            ["parse_shards.tenant_id", "parse_shards.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "selected_attempt_id"],
            ["parse_attempts.tenant_id", "parse_attempts.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "decision_key"),
        CheckConstraint(
            "decision IN ('selected','unresolved','recovery_required','quarantined')",
            name="ck_arbitration_decisions_decision",
        ),
        CheckConstraint(
            "authority_tier IN ("
            "'exact_authority','native','pixel_ocr','independent_agreement','none')",
            name="ck_arbitration_decisions_authority",
        ),
        CheckConstraint(
            "(decision = 'selected' AND selected_attempt_id IS NOT NULL "
            "AND authority_tier <> 'none') OR "
            "(decision <> 'selected' AND selected_attempt_id IS NULL)",
            name="ck_arbitration_decisions_selection",
        ),
        CheckConstraint(
            "length(evidence_sha256) = 64", name="ck_arbitration_decisions_evidence_sha"
        ),
        CheckConstraint(
            "length(logical_unit_sha256) = 64",
            name="ck_arbitration_decisions_logical_unit_sha",
        ),
        CheckConstraint(
            "(decision = 'selected' AND priced_credit_amount > 0) OR "
            "(decision <> 'selected' AND priced_credit_amount = 0)",
            name="ck_arbitration_decisions_priced_credit",
        ),
        Index("arbitration_decisions_shard_idx", "shard_id", "created_at"),
    )
