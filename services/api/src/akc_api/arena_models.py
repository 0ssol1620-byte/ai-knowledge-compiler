"""Persistence models for immutable Arena evidence and production route outcomes.

The research ledger intentionally has no tenant source-file foreign key. Public
benchmark inputs are identified by immutable artifact references and digests.
Customer production outcomes live in a separate tenant/project table and carry
only permission and decision receipts; they cannot become Arena cases by FK or
by an ``eligible`` flag.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
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


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid4() -> uuid.UUID:
    return uuid.uuid4()


class ArenaCampaign(Base):
    """Mutable lifecycle pointer over one otherwise immutable campaign identity."""

    __tablename__ = "arena_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid4)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    corpus_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(120), nullable=False)
    protocol_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", nullable=False)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_receipt_sha256: Mapped[str | None] = mapped_column(String(64))
    outcome_counts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint("length(corpus_manifest_sha256) = 64", name="ck_arena_campaign_manifest"),
        CheckConstraint("length(protocol_sha256) = 64", name="ck_arena_campaign_protocol"),
        CheckConstraint(
            "status IN ('DRAFT','FROZEN','RUNNING','FINALIZED','FAILED','CANCELLED')",
            name="ck_arena_campaign_status",
        ),
        CheckConstraint(
            "(status = 'DRAFT' AND frozen_at IS NULL AND started_at IS NULL "
            "AND finalized_at IS NULL AND terminal_receipt_sha256 IS NULL) OR "
            "(status = 'FROZEN' AND frozen_at IS NOT NULL AND started_at IS NULL "
            "AND finalized_at IS NULL AND terminal_receipt_sha256 IS NULL) OR "
            "(status = 'RUNNING' AND frozen_at IS NOT NULL AND started_at IS NOT NULL "
            "AND finalized_at IS NULL AND terminal_receipt_sha256 IS NULL) OR "
            "(status IN ('FINALIZED','FAILED','CANCELLED') AND frozen_at IS NOT NULL "
            "AND finalized_at IS NOT NULL AND terminal_receipt_sha256 IS NOT NULL)",
            name="ck_arena_campaign_lifecycle_shape",
        ),
        CheckConstraint(
            "terminal_receipt_sha256 IS NULL OR length(terminal_receipt_sha256) = 64",
            name="ck_arena_campaign_terminal_receipt",
        ),
    )


class ArenaCampaignStateEvent(Base):
    """Append-only campaign transition evidence."""

    __tablename__ = "arena_campaign_state_events"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("arena_campaigns.id", ondelete="RESTRICT"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    transition_receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint("sequence >= 0", name="ck_arena_campaign_event_sequence"),
        CheckConstraint("length(transition_receipt_sha256) = 64", name="ck_arena_event_receipt"),
        CheckConstraint(
            "to_status IN ('DRAFT','FROZEN','RUNNING','FINALIZED','FAILED','CANCELLED')",
            name="ck_arena_event_to_status",
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('DRAFT','FROZEN','RUNNING','FINALIZED','FAILED','CANCELLED')",
            name="ck_arena_event_from_status",
        ),
    )


class ArenaCase(Base):
    """One hash-bound case in a campaign manifest; rows are append-only."""

    __tablename__ = "arena_cases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("arena_campaigns.id", ondelete="RESTRICT"), nullable=False
    )
    document_family_id: Mapped[str] = mapped_column(String(200), nullable=False)
    page_or_document_id: Mapped[str] = mapped_column(String(240), nullable=False)
    split: Mapped[str] = mapped_column(String(24), nullable=False)
    origin: Mapped[str] = mapped_column(String(40), nullable=False)
    slice_labels: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    risk_class: Mapped[str] = mapped_column(String(24), nullable=False)
    source_artifact_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    source_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    truth_ref: Mapped[str | None] = mapped_column(String(500))
    license_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    case_manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("campaign_id", "id"),
        UniqueConstraint(
            "campaign_id", "page_or_document_id", name="uq_arena_case_campaign_object"
        ),
        UniqueConstraint(
            "campaign_id", "case_manifest_sha256", name="uq_arena_case_campaign_manifest"
        ),
        CheckConstraint(
            "split IN ('CALIBRATION','EVAL','ROUTER_TRAIN','ROUTER_HOLDOUT')",
            name="ck_arena_case_split",
        ),
        CheckConstraint(
            "origin IN ('OLMOCR','OMNIDOC','PARSEBENCH','DART','SEC','FAILURE_ZOO',"
            "'CLEAN_CONTROL','OTHER_PUBLIC')",
            name="ck_arena_case_origin",
        ),
        CheckConstraint("risk_class IN ('LOW','MEDIUM','HIGH')", name="ck_arena_case_risk"),
        CheckConstraint("length(source_artifact_sha256) = 64", name="ck_arena_case_source_sha"),
        CheckConstraint("length(case_manifest_sha256) = 64", name="ck_arena_case_manifest_sha"),
        Index("arena_cases_campaign_split_idx", "campaign_id", "split", "id"),
        Index("arena_cases_family_idx", "campaign_id", "document_family_id", "split"),
    )


class ArenaRun(Base):
    """Exact model/input/prompt/price identity plus one terminal outcome."""

    __tablename__ = "arena_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    model_registry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("model_registry.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    exact_model_id: Mapped[str] = mapped_column(String(240), nullable=False)
    exact_model_revision: Mapped[str] = mapped_column(String(200), nullable=False)
    input_track: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_track: Mapped[str] = mapped_column(String(40), nullable=False)
    batch_mode: Mapped[bool] = mapped_column(Boolean, nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    settings_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_artifact_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    input_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    price_snapshot_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    price_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_output_artifact_ref: Mapped[str | None] = mapped_column(String(500))
    raw_output_sha256: Mapped[str | None] = mapped_column(String(64))
    normalized_output_artifact_ref: Mapped[str | None] = mapped_column(String(500))
    normalized_output_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="RUNNING", nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(BigInteger)
    input_units: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    output_units: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    actual_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    error_code: Mapped[str | None] = mapped_column(String(120))
    terminal_receipt_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["campaign_id", "case_id"],
            ["arena_cases.campaign_id", "arena_cases.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("campaign_id", "id"),
        UniqueConstraint(
            "campaign_id", "idempotency_key", name="uq_arena_run_campaign_idempotency"
        ),
        CheckConstraint(
            "input_track IN ('STANDARD_IMAGE','NATIVE_PROVIDER','NATIVE_LOCAL')",
            name="ck_arena_run_input_track",
        ),
        CheckConstraint(
            "prompt_track IN ('STANDARD','PROVIDER_OPTIMIZED')",
            name="ck_arena_run_prompt_track",
        ),
        CheckConstraint(
            "status IN ('RUNNING','SUCCESS','PROVIDER_ERROR','TRUNCATED','INVALID_OUTPUT',"
            "'CANCELLED')",
            name="ck_arena_run_status",
        ),
        CheckConstraint("length(prompt_sha256) = 64", name="ck_arena_run_prompt_sha"),
        CheckConstraint("length(schema_sha256) = 64", name="ck_arena_run_schema_sha"),
        CheckConstraint("length(settings_sha256) = 64", name="ck_arena_run_settings_sha"),
        CheckConstraint("length(input_artifact_sha256) = 64", name="ck_arena_run_input_sha"),
        CheckConstraint("length(price_snapshot_sha256) = 64", name="ck_arena_run_price_sha"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_arena_run_latency"),
        CheckConstraint(
            "actual_cost_usd IS NULL OR actual_cost_usd >= 0", name="ck_arena_run_cost"
        ),
        CheckConstraint(
            "(raw_output_artifact_ref IS NULL AND raw_output_sha256 IS NULL) OR "
            "(raw_output_artifact_ref IS NOT NULL AND length(raw_output_sha256) = 64)",
            name="ck_arena_run_raw_artifact",
        ),
        CheckConstraint(
            "(normalized_output_artifact_ref IS NULL AND normalized_output_sha256 IS NULL) OR "
            "(normalized_output_artifact_ref IS NOT NULL "
            "AND length(normalized_output_sha256) = 64)",
            name="ck_arena_run_normalized_artifact",
        ),
        CheckConstraint(
            "(status = 'RUNNING' AND completed_at IS NULL AND latency_ms IS NULL "
            "AND input_units IS NULL AND output_units IS NULL AND actual_cost_usd IS NULL "
            "AND terminal_receipt_sha256 IS NULL AND error_code IS NULL) OR "
            "(status = 'SUCCESS' AND completed_at IS NOT NULL AND latency_ms IS NOT NULL "
            "AND input_units IS NOT NULL AND output_units IS NOT NULL "
            "AND actual_cost_usd IS NOT NULL AND terminal_receipt_sha256 IS NOT NULL "
            "AND raw_output_artifact_ref IS NOT NULL "
            "AND normalized_output_artifact_ref IS NOT NULL AND error_code IS NULL) OR "
            "(status IN ('PROVIDER_ERROR','TRUNCATED','INVALID_OUTPUT','CANCELLED') "
            "AND completed_at IS NOT NULL AND latency_ms IS NOT NULL "
            "AND input_units IS NOT NULL AND output_units IS NOT NULL "
            "AND actual_cost_usd IS NOT NULL AND terminal_receipt_sha256 IS NOT NULL "
            "AND error_code IS NOT NULL)",
            name="ck_arena_run_outcome_complete",
        ),
        CheckConstraint(
            "terminal_receipt_sha256 IS NULL OR length(terminal_receipt_sha256) = 64",
            name="ck_arena_run_terminal_receipt",
        ),
        Index("arena_runs_campaign_status_idx", "campaign_id", "status", "id"),
        Index("arena_runs_case_model_idx", "case_id", "model_registry_id", "id"),
    )


class ArenaScore(Base):
    """Append-only evaluator result pinned to evaluator identity and receipt."""

    __tablename__ = "arena_scores"

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("arena_runs.id", ondelete="RESTRICT"), primary_key=True
    )
    evaluator_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    evaluator_revision: Mapped[str] = mapped_column(String(200), primary_key=True)
    metric_name: Mapped[str] = mapped_column(String(160), primary_key=True)
    value: Mapped[float | None] = mapped_column(Float)
    severity: Mapped[str | None] = mapped_column(String(24))
    evaluator_artifact_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    evaluator_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "value IS NOT NULL OR severity IS NOT NULL", name="ck_arena_score_has_outcome"
        ),
        CheckConstraint(
            "severity IS NULL OR severity IN ('INFO','WARNING','CRITICAL')",
            name="ck_arena_score_severity",
        ),
        CheckConstraint(
            "length(evaluator_artifact_sha256) = 64", name="ck_arena_score_evaluator_sha"
        ),
        CheckConstraint("length(receipt_sha256) = 64", name="ck_arena_score_receipt_sha"),
        Index("arena_scores_metric_idx", "metric_name", "evaluator_id", "run_id"),
    )


class ProductionRouteOutcome(Base):
    """Append-only permissioned production routing receipt, isolated from research."""

    __tablename__ = "production_route_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    collection_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    processing_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    shard_id: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    requested_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    executable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    outcome_status: Mapped[str] = mapped_column(String(24), nullable=False)
    selected_path: Mapped[str | None] = mapped_column(String(160))
    selected_model_registry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("model_registry.id", ondelete="RESTRICT")
    )
    policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    policy_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    authority_envelope_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    permission_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    route_receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    fail_closed_reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    shadow_counterfactual: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    trusted: Mapped[bool | None] = mapped_column(Boolean)
    latency_ms: Mapped[int | None] = mapped_column(BigInteger)
    actual_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    research_use_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "workspace_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "collection_id"],
            ["collections.tenant_id", "collections.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "processing_job_id"],
            ["processing_jobs.tenant_id", "processing_jobs.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint(
            "tenant_id", "workspace_id", "idempotency_key", name="uq_route_outcome_idempotency"
        ),
        CheckConstraint(
            "decision_kind IN ('DETERMINISTIC','ADAPTIVE')", name="ck_route_outcome_decision_kind"
        ),
        CheckConstraint(
            "outcome_status IN ('EXECUTED','FAILED','ABSTAINED','SHADOW_ONLY')",
            name="ck_route_outcome_status",
        ),
        CheckConstraint(
            "(executable AND outcome_status IN ('EXECUTED','FAILED')) OR "
            "(NOT executable AND outcome_status IN ('ABSTAINED','SHADOW_ONLY'))",
            name="ck_route_outcome_execution_shape",
        ),
        CheckConstraint(
            "(outcome_status = 'EXECUTED' AND selected_path IS NOT NULL "
            "AND trusted IS NOT NULL AND latency_ms IS NOT NULL "
            "AND actual_cost_usd IS NOT NULL) OR outcome_status <> 'EXECUTED'",
            name="ck_route_outcome_execution_complete",
        ),
        CheckConstraint(
            "(outcome_status IN ('FAILED','ABSTAINED') "
            "AND json_array_length(fail_closed_reason_codes) > 0) OR "
            "outcome_status NOT IN ('FAILED','ABSTAINED')",
            name="ck_route_outcome_failure_reason",
        ),
        CheckConstraint("length(policy_sha256) = 64", name="ck_route_outcome_policy_sha"),
        CheckConstraint(
            "length(authority_envelope_sha256) = 64", name="ck_route_outcome_authority_sha"
        ),
        CheckConstraint(
            "length(permission_snapshot_sha256) = 64", name="ck_route_outcome_permission_sha"
        ),
        CheckConstraint("length(route_receipt_sha256) = 64", name="ck_route_outcome_receipt_sha"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_route_outcome_latency"),
        CheckConstraint(
            "actual_cost_usd IS NULL OR actual_cost_usd >= 0", name="ck_route_outcome_cost"
        ),
        CheckConstraint("research_use_allowed = false", name="ck_route_outcome_no_research_use"),
        Index(
            "production_route_outcomes_workspace_idx",
            "tenant_id",
            "workspace_id",
            "collection_id",
            "processing_job_id",
            "created_at",
            "id",
        ),
        Index(
            "production_route_outcomes_job_shard_idx",
            "tenant_id",
            "processing_job_id",
            "shard_id",
            "created_at",
        ),
        Index("production_route_outcomes_policy_idx", "policy_version", "created_at"),
    )
