"""Add immutable Arena evidence and isolated production route outcomes.

Revision ID: 0041_arena_persistence
Revises: 0037_gpu_post_claim_authorization
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0041_arena_persistence"
down_revision = "0040_source_cursor_tenancy"
branch_labels = None
depends_on = None

_APPEND_ONLY = (
    "arena_campaign_state_events",
    "arena_cases",
    "arena_scores",
    "production_route_outcomes",
)


def _create_tables() -> None:
    expected = {
        "arena_campaigns",
        "arena_campaign_state_events",
        "arena_cases",
        "arena_runs",
        "arena_scores",
        "production_route_outcomes",
    }
    present = expected & set(inspect(op.get_bind()).get_table_names())
    # Revision 0001 creates current Base.metadata on a new database. A fresh
    # install running current code therefore already has this complete set by
    # the time 0038 is reached; an existing deployment has none of it.
    if present == expected:
        return
    if present:
        raise RuntimeError(f"partial Arena schema exists before 0038: {sorted(present)}")
    op.create_table(
        "arena_campaigns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("corpus_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("protocol_version", sa.String(length=120), nullable=False),
        sa.Column("protocol_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="DRAFT", nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_receipt_sha256", sa.String(length=64), nullable=True),
        sa.Column("outcome_counts", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "length(corpus_manifest_sha256) = 64", name="ck_arena_campaign_manifest"
        ),
        sa.CheckConstraint("length(protocol_sha256) = 64", name="ck_arena_campaign_protocol"),
        sa.CheckConstraint(
            "status IN ('DRAFT','FROZEN','RUNNING','FINALIZED','FAILED','CANCELLED')",
            name="ck_arena_campaign_status",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "terminal_receipt_sha256 IS NULL OR length(terminal_receipt_sha256) = 64",
            name="ck_arena_campaign_terminal_receipt",
        ),
    )
    op.create_table(
        "arena_campaign_state_events",
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(length=24), nullable=True),
        sa.Column("to_status", sa.String(length=24), nullable=False),
        sa.Column("transition_receipt_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["arena_campaigns.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("campaign_id", "sequence"),
        sa.CheckConstraint("sequence >= 0", name="ck_arena_campaign_event_sequence"),
        sa.CheckConstraint(
            "length(transition_receipt_sha256) = 64", name="ck_arena_event_receipt"
        ),
        sa.CheckConstraint(
            "to_status IN ('DRAFT','FROZEN','RUNNING','FINALIZED','FAILED','CANCELLED')",
            name="ck_arena_event_to_status",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN "
            "('DRAFT','FROZEN','RUNNING','FINALIZED','FAILED','CANCELLED')",
            name="ck_arena_event_from_status",
        ),
    )
    op.create_table(
        "arena_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("document_family_id", sa.String(length=200), nullable=False),
        sa.Column("page_or_document_id", sa.String(length=240), nullable=False),
        sa.Column("split", sa.String(length=24), nullable=False),
        sa.Column("origin", sa.String(length=40), nullable=False),
        sa.Column("slice_labels", sa.JSON(), nullable=False),
        sa.Column("risk_class", sa.String(length=24), nullable=False),
        sa.Column("source_artifact_ref", sa.String(length=500), nullable=False),
        sa.Column("source_artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("truth_ref", sa.String(length=500), nullable=True),
        sa.Column("license_ref", sa.String(length=500), nullable=False),
        sa.Column("case_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["arena_campaigns.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "id"),
        sa.UniqueConstraint(
            "campaign_id", "page_or_document_id", name="uq_arena_case_campaign_object"
        ),
        sa.UniqueConstraint(
            "campaign_id", "case_manifest_sha256", name="uq_arena_case_campaign_manifest"
        ),
        sa.CheckConstraint(
            "split IN ('CALIBRATION','EVAL','ROUTER_TRAIN','ROUTER_HOLDOUT')",
            name="ck_arena_case_split",
        ),
        sa.CheckConstraint(
            "origin IN ('OLMOCR','OMNIDOC','PARSEBENCH','DART','SEC','FAILURE_ZOO',"
            "'CLEAN_CONTROL','OTHER_PUBLIC')",
            name="ck_arena_case_origin",
        ),
        sa.CheckConstraint("risk_class IN ('LOW','MEDIUM','HIGH')", name="ck_arena_case_risk"),
        sa.CheckConstraint("length(source_artifact_sha256) = 64", name="ck_arena_case_source_sha"),
        sa.CheckConstraint("length(case_manifest_sha256) = 64", name="ck_arena_case_manifest_sha"),
    )
    op.create_index(
        "arena_cases_campaign_split_idx", "arena_cases", ["campaign_id", "split", "id"]
    )
    op.create_index(
        "arena_cases_family_idx",
        "arena_cases",
        ["campaign_id", "document_family_id", "split"],
    )
    op.create_table(
        "arena_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("model_registry_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("exact_model_id", sa.String(length=240), nullable=False),
        sa.Column("exact_model_revision", sa.String(length=200), nullable=False),
        sa.Column("input_track", sa.String(length=40), nullable=False),
        sa.Column("prompt_track", sa.String(length=40), nullable=False),
        sa.Column("batch_mode", sa.Boolean(), nullable=False),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("schema_sha256", sa.String(length=64), nullable=False),
        sa.Column("settings_sha256", sa.String(length=64), nullable=False),
        sa.Column("input_artifact_ref", sa.String(length=500), nullable=False),
        sa.Column("input_artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("price_snapshot_ref", sa.String(length=500), nullable=False),
        sa.Column("price_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("raw_output_artifact_ref", sa.String(length=500), nullable=True),
        sa.Column("raw_output_sha256", sa.String(length=64), nullable=True),
        sa.Column("normalized_output_artifact_ref", sa.String(length=500), nullable=True),
        sa.Column("normalized_output_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="RUNNING", nullable=False),
        sa.Column("latency_ms", sa.BigInteger(), nullable=True),
        sa.Column("input_units", sa.JSON(), nullable=True),
        sa.Column("output_units", sa.JSON(), nullable=True),
        sa.Column("actual_cost_usd", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("terminal_receipt_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["campaign_id", "case_id"],
            ["arena_cases.campaign_id", "arena_cases.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_registry_id"], ["model_registry.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "id"),
        sa.UniqueConstraint(
            "campaign_id", "idempotency_key", name="uq_arena_run_campaign_idempotency"
        ),
        sa.CheckConstraint(
            "input_track IN ('STANDARD_IMAGE','NATIVE_PROVIDER','NATIVE_LOCAL')",
            name="ck_arena_run_input_track",
        ),
        sa.CheckConstraint(
            "prompt_track IN ('STANDARD','PROVIDER_OPTIMIZED')",
            name="ck_arena_run_prompt_track",
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING','SUCCESS','PROVIDER_ERROR','TRUNCATED','INVALID_OUTPUT',"
            "'CANCELLED')",
            name="ck_arena_run_status",
        ),
        sa.CheckConstraint("length(prompt_sha256) = 64", name="ck_arena_run_prompt_sha"),
        sa.CheckConstraint("length(schema_sha256) = 64", name="ck_arena_run_schema_sha"),
        sa.CheckConstraint("length(settings_sha256) = 64", name="ck_arena_run_settings_sha"),
        sa.CheckConstraint("length(input_artifact_sha256) = 64", name="ck_arena_run_input_sha"),
        sa.CheckConstraint("length(price_snapshot_sha256) = 64", name="ck_arena_run_price_sha"),
        sa.CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_arena_run_latency"),
        sa.CheckConstraint(
            "actual_cost_usd IS NULL OR actual_cost_usd >= 0", name="ck_arena_run_cost"
        ),
        sa.CheckConstraint(
            "(raw_output_artifact_ref IS NULL AND raw_output_sha256 IS NULL) OR "
            "(raw_output_artifact_ref IS NOT NULL AND length(raw_output_sha256) = 64)",
            name="ck_arena_run_raw_artifact",
        ),
        sa.CheckConstraint(
            "(normalized_output_artifact_ref IS NULL AND normalized_output_sha256 IS NULL) OR "
            "(normalized_output_artifact_ref IS NOT NULL "
            "AND length(normalized_output_sha256) = 64)",
            name="ck_arena_run_normalized_artifact",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "terminal_receipt_sha256 IS NULL OR length(terminal_receipt_sha256) = 64",
            name="ck_arena_run_terminal_receipt",
        ),
    )
    op.create_index(
        "arena_runs_campaign_status_idx", "arena_runs", ["campaign_id", "status", "id"]
    )
    op.create_index(
        "arena_runs_case_model_idx", "arena_runs", ["case_id", "model_registry_id", "id"]
    )
    op.create_table(
        "arena_scores",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("evaluator_id", sa.String(length=200), nullable=False),
        sa.Column("evaluator_revision", sa.String(length=200), nullable=False),
        sa.Column("metric_name", sa.String(length=160), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("severity", sa.String(length=24), nullable=True),
        sa.Column("evaluator_artifact_ref", sa.String(length=500), nullable=False),
        sa.Column("evaluator_artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("receipt_ref", sa.String(length=500), nullable=False),
        sa.Column("receipt_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["run_id"], ["arena_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("run_id", "evaluator_id", "evaluator_revision", "metric_name"),
        sa.CheckConstraint(
            "value IS NOT NULL OR severity IS NOT NULL", name="ck_arena_score_has_outcome"
        ),
        sa.CheckConstraint(
            "severity IS NULL OR severity IN ('INFO','WARNING','CRITICAL')",
            name="ck_arena_score_severity",
        ),
        sa.CheckConstraint(
            "length(evaluator_artifact_sha256) = 64", name="ck_arena_score_evaluator_sha"
        ),
        sa.CheckConstraint("length(receipt_sha256) = 64", name="ck_arena_score_receipt_sha"),
    )
    op.create_index(
        "arena_scores_metric_idx", "arena_scores", ["metric_name", "evaluator_id", "run_id"]
    )
    op.create_table(
        "production_route_outcomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("processing_job_id", sa.Uuid(), nullable=False),
        sa.Column("shard_id", sa.String(length=200), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("requested_mode", sa.String(length=32), nullable=False),
        sa.Column("effective_mode", sa.String(length=32), nullable=False),
        sa.Column("decision_kind", sa.String(length=24), nullable=False),
        sa.Column("executable", sa.Boolean(), nullable=False),
        sa.Column("outcome_status", sa.String(length=24), nullable=False),
        sa.Column("selected_path", sa.String(length=160), nullable=True),
        sa.Column("selected_model_registry_id", sa.Uuid(), nullable=True),
        sa.Column("policy_version", sa.String(length=120), nullable=False),
        sa.Column("policy_sha256", sa.String(length=64), nullable=False),
        sa.Column("authority_envelope_sha256", sa.String(length=64), nullable=False),
        sa.Column("permission_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("route_receipt_sha256", sa.String(length=64), nullable=False),
        sa.Column("fail_closed_reason_codes", sa.JSON(), nullable=False),
        sa.Column("shadow_counterfactual", sa.JSON(), nullable=True),
        sa.Column("trusted", sa.Boolean(), nullable=True),
        sa.Column("latency_ms", sa.BigInteger(), nullable=True),
        sa.Column("actual_cost_usd", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("research_use_allowed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "workspace_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "collection_id"],
            ["collections.tenant_id", "collections.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "processing_job_id"],
            ["processing_jobs.tenant_id", "processing_jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selected_model_registry_id"], ["model_registry.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.UniqueConstraint(
            "tenant_id", "workspace_id", "idempotency_key", name="uq_route_outcome_idempotency"
        ),
        sa.CheckConstraint(
            "decision_kind IN ('DETERMINISTIC','ADAPTIVE')", name="ck_route_outcome_decision_kind"
        ),
        sa.CheckConstraint(
            "outcome_status IN ('EXECUTED','FAILED','ABSTAINED','SHADOW_ONLY')",
            name="ck_route_outcome_status",
        ),
        sa.CheckConstraint(
            "(executable AND outcome_status IN ('EXECUTED','FAILED')) OR "
            "(NOT executable AND outcome_status IN ('ABSTAINED','SHADOW_ONLY'))",
            name="ck_route_outcome_execution_shape",
        ),
        sa.CheckConstraint(
            "(outcome_status = 'EXECUTED' AND selected_path IS NOT NULL "
            "AND trusted IS NOT NULL AND latency_ms IS NOT NULL "
            "AND actual_cost_usd IS NOT NULL) OR outcome_status <> 'EXECUTED'",
            name="ck_route_outcome_execution_complete",
        ),
        sa.CheckConstraint(
            "(outcome_status IN ('FAILED','ABSTAINED') "
            "AND json_array_length(fail_closed_reason_codes) > 0) OR "
            "outcome_status NOT IN ('FAILED','ABSTAINED')",
            name="ck_route_outcome_failure_reason",
        ),
        sa.CheckConstraint("length(policy_sha256) = 64", name="ck_route_outcome_policy_sha"),
        sa.CheckConstraint(
            "length(authority_envelope_sha256) = 64", name="ck_route_outcome_authority_sha"
        ),
        sa.CheckConstraint(
            "length(permission_snapshot_sha256) = 64", name="ck_route_outcome_permission_sha"
        ),
        sa.CheckConstraint(
            "length(route_receipt_sha256) = 64", name="ck_route_outcome_receipt_sha"
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="ck_route_outcome_latency"
        ),
        sa.CheckConstraint(
            "actual_cost_usd IS NULL OR actual_cost_usd >= 0", name="ck_route_outcome_cost"
        ),
        sa.CheckConstraint("research_use_allowed = false", name="ck_route_outcome_no_research_use"),
    )
    op.create_index(
        "production_route_outcomes_workspace_idx",
        "production_route_outcomes",
        [
            "tenant_id",
            "workspace_id",
            "collection_id",
            "processing_job_id",
            "created_at",
            "id",
        ],
    )
    op.create_index(
        "production_route_outcomes_job_shard_idx",
        "production_route_outcomes",
        ["tenant_id", "processing_job_id", "shard_id", "created_at"],
    )
    op.create_index(
        "production_route_outcomes_policy_idx",
        "production_route_outcomes",
        ["policy_version", "created_at"],
    )


def _create_postgres_guards() -> None:
    for table in _APPEND_ONLY:
        op.execute(
            f"""
            CREATE FUNCTION {table}_reject_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION '{table} is append-only';
            END;
            $$
            """
        )
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {table}_reject_mutation()"
        )
    op.execute(
        """
        CREATE FUNCTION arena_campaigns_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'arena campaigns cannot be deleted';
            END IF;
            IF OLD.name IS DISTINCT FROM NEW.name
               OR OLD.corpus_manifest_sha256 IS DISTINCT FROM NEW.corpus_manifest_sha256
               OR OLD.protocol_version IS DISTINCT FROM NEW.protocol_version
               OR OLD.protocol_sha256 IS DISTINCT FROM NEW.protocol_sha256
               OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
                RAISE EXCEPTION 'arena campaign identity is immutable';
            END IF;
            IF OLD.status IN ('FINALIZED','FAILED','CANCELLED')
               OR NOT ((OLD.status = 'DRAFT' AND NEW.status = 'FROZEN')
                    OR (OLD.status = 'FROZEN' AND NEW.status = 'RUNNING')
                    OR (OLD.status = 'RUNNING'
                        AND NEW.status IN ('FINALIZED','FAILED','CANCELLED'))) THEN
                RAISE EXCEPTION 'illegal arena campaign transition';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER arena_campaigns_state_guard BEFORE UPDATE OR DELETE ON arena_campaigns "
        "FOR EACH ROW EXECUTE FUNCTION arena_campaigns_guard()"
    )
    op.execute(
        """
        CREATE FUNCTION arena_runs_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'arena runs cannot be deleted';
            END IF;
            IF OLD.campaign_id IS DISTINCT FROM NEW.campaign_id
               OR OLD.case_id IS DISTINCT FROM NEW.case_id
               OR OLD.model_registry_id IS DISTINCT FROM NEW.model_registry_id
               OR OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key
               OR OLD.exact_model_id IS DISTINCT FROM NEW.exact_model_id
               OR OLD.exact_model_revision IS DISTINCT FROM NEW.exact_model_revision
               OR OLD.input_track IS DISTINCT FROM NEW.input_track
               OR OLD.prompt_track IS DISTINCT FROM NEW.prompt_track
               OR OLD.batch_mode IS DISTINCT FROM NEW.batch_mode
               OR OLD.prompt_sha256 IS DISTINCT FROM NEW.prompt_sha256
               OR OLD.schema_sha256 IS DISTINCT FROM NEW.schema_sha256
               OR OLD.settings_sha256 IS DISTINCT FROM NEW.settings_sha256
               OR OLD.input_artifact_ref IS DISTINCT FROM NEW.input_artifact_ref
               OR OLD.input_artifact_sha256 IS DISTINCT FROM NEW.input_artifact_sha256
               OR OLD.price_snapshot_ref IS DISTINCT FROM NEW.price_snapshot_ref
               OR OLD.price_snapshot_sha256 IS DISTINCT FROM NEW.price_snapshot_sha256
               OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
                RAISE EXCEPTION 'arena run identity is immutable';
            END IF;
            IF OLD.status <> 'RUNNING' OR NEW.status = 'RUNNING' THEN
                RAISE EXCEPTION 'arena run outcome is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER arena_runs_state_guard BEFORE UPDATE OR DELETE ON arena_runs "
        "FOR EACH ROW EXECUTE FUNCTION arena_runs_guard()"
    )
    op.execute(
        """
        CREATE FUNCTION arena_cases_draft_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM arena_campaigns
                WHERE id = NEW.campaign_id AND status = 'DRAFT'
            ) THEN
                RAISE EXCEPTION 'arena cases require a draft campaign';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER arena_cases_insert_guard BEFORE INSERT ON arena_cases "
        "FOR EACH ROW EXECUTE FUNCTION arena_cases_draft_guard()"
    )


def _create_sqlite_guards() -> None:
    for table in _APPEND_ONLY:
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {table}_append_only_{operation.lower()} "
                f"BEFORE {operation} ON {table} BEGIN "
                f"SELECT RAISE(ABORT, '{table} is append-only'); END"
            )
    op.execute(
        "CREATE TRIGGER arena_campaigns_delete_guard BEFORE DELETE ON arena_campaigns "
        "BEGIN SELECT RAISE(ABORT, 'arena campaigns cannot be deleted'); END"
    )
    op.execute(
        """
        CREATE TRIGGER arena_campaigns_state_guard BEFORE UPDATE ON arena_campaigns
        WHEN OLD.name IS NOT NEW.name
          OR OLD.corpus_manifest_sha256 IS NOT NEW.corpus_manifest_sha256
          OR OLD.protocol_version IS NOT NEW.protocol_version
          OR OLD.protocol_sha256 IS NOT NEW.protocol_sha256
          OR OLD.created_at IS NOT NEW.created_at
          OR OLD.status IN ('FINALIZED','FAILED','CANCELLED')
          OR NOT ((OLD.status = 'DRAFT' AND NEW.status = 'FROZEN')
               OR (OLD.status = 'FROZEN' AND NEW.status = 'RUNNING')
               OR (OLD.status = 'RUNNING'
                   AND NEW.status IN ('FINALIZED','FAILED','CANCELLED')))
        BEGIN SELECT RAISE(ABORT, 'illegal or identity-changing arena campaign update'); END
        """
    )
    op.execute(
        "CREATE TRIGGER arena_runs_delete_guard BEFORE DELETE ON arena_runs "
        "BEGIN SELECT RAISE(ABORT, 'arena runs cannot be deleted'); END"
    )
    op.execute(
        """
        CREATE TRIGGER arena_runs_state_guard BEFORE UPDATE ON arena_runs
        WHEN OLD.campaign_id IS NOT NEW.campaign_id
          OR OLD.case_id IS NOT NEW.case_id
          OR OLD.model_registry_id IS NOT NEW.model_registry_id
          OR OLD.idempotency_key IS NOT NEW.idempotency_key
          OR OLD.exact_model_id IS NOT NEW.exact_model_id
          OR OLD.exact_model_revision IS NOT NEW.exact_model_revision
          OR OLD.input_track IS NOT NEW.input_track
          OR OLD.prompt_track IS NOT NEW.prompt_track
          OR OLD.batch_mode IS NOT NEW.batch_mode
          OR OLD.prompt_sha256 IS NOT NEW.prompt_sha256
          OR OLD.schema_sha256 IS NOT NEW.schema_sha256
          OR OLD.settings_sha256 IS NOT NEW.settings_sha256
          OR OLD.input_artifact_ref IS NOT NEW.input_artifact_ref
          OR OLD.input_artifact_sha256 IS NOT NEW.input_artifact_sha256
          OR OLD.price_snapshot_ref IS NOT NEW.price_snapshot_ref
          OR OLD.price_snapshot_sha256 IS NOT NEW.price_snapshot_sha256
          OR OLD.created_at IS NOT NEW.created_at
          OR OLD.status <> 'RUNNING'
          OR NEW.status = 'RUNNING'
        BEGIN SELECT RAISE(ABORT, 'illegal or identity-changing arena run update'); END
        """
    )
    op.execute(
        """
        CREATE TRIGGER arena_cases_insert_guard BEFORE INSERT ON arena_cases
        WHEN NOT EXISTS (
            SELECT 1 FROM arena_campaigns
            WHERE id = NEW.campaign_id AND status = 'DRAFT'
        )
        BEGIN SELECT RAISE(ABORT, 'arena cases require a draft campaign'); END
        """
    )


def _configure_postgres_access() -> None:
    op.execute("GRANT SELECT, INSERT, UPDATE ON arena_campaigns TO akc_scheduler")
    op.execute("GRANT SELECT, INSERT ON arena_campaign_state_events TO akc_scheduler")
    op.execute("GRANT SELECT, INSERT ON arena_cases TO akc_scheduler")
    op.execute("GRANT SELECT, INSERT, UPDATE ON arena_runs TO akc_scheduler")
    op.execute("GRANT SELECT, INSERT ON arena_scores TO akc_scheduler")
    op.execute("GRANT SELECT, INSERT ON production_route_outcomes TO akc_scheduler")
    op.execute("GRANT SELECT ON production_route_outcomes TO akc_api_plane")
    # The scheduler is deliberately still BYPASSRLS until the separately gated
    # worker-arming phase.  The API plane is NOBYPASSRLS and exercises tenant
    # filtering today; this scheduler policy becomes effective after arming.
    op.execute("ALTER TABLE production_route_outcomes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE production_route_outcomes FORCE ROW LEVEL SECURITY")
    tenant = (
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    )
    op.execute(
        "CREATE POLICY production_route_outcomes_tenant_isolation "
        "ON production_route_outcomes AS RESTRICTIVE TO PUBLIC "
        f"USING ({tenant}) WITH CHECK ({tenant})"
    )
    op.execute(
        "CREATE POLICY production_route_outcomes_runtime_access "
        "ON production_route_outcomes AS PERMISSIVE FOR ALL TO akc_scheduler, akc_api_plane "
        f"USING ({tenant}) WITH CHECK ({tenant})"
    )


def upgrade() -> None:
    _create_tables()
    if op.get_bind().dialect.name == "postgresql":
        _create_postgres_guards()
        _configure_postgres_access()
    else:
        _create_sqlite_guards()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "DROP POLICY IF EXISTS production_route_outcomes_runtime_access "
            "ON production_route_outcomes"
        )
        op.execute(
            "DROP POLICY IF EXISTS production_route_outcomes_tenant_isolation "
            "ON production_route_outcomes"
        )
        op.execute("DROP TRIGGER IF EXISTS arena_runs_state_guard ON arena_runs")
        op.execute("DROP FUNCTION IF EXISTS arena_runs_guard()")
        op.execute("DROP TRIGGER IF EXISTS arena_campaigns_state_guard ON arena_campaigns")
        op.execute("DROP FUNCTION IF EXISTS arena_campaigns_guard()")
        op.execute("DROP TRIGGER IF EXISTS arena_cases_insert_guard ON arena_cases")
        op.execute("DROP FUNCTION IF EXISTS arena_cases_draft_guard()")
        for table in _APPEND_ONLY:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_reject_mutation()")
    else:
        op.execute("DROP TRIGGER IF EXISTS arena_runs_state_guard")
        op.execute("DROP TRIGGER IF EXISTS arena_runs_delete_guard")
        op.execute("DROP TRIGGER IF EXISTS arena_campaigns_state_guard")
        op.execute("DROP TRIGGER IF EXISTS arena_campaigns_delete_guard")
        op.execute("DROP TRIGGER IF EXISTS arena_cases_insert_guard")
        for table in _APPEND_ONLY:
            for operation in ("update", "delete"):
                op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only_{operation}")
    for table in (
        "production_route_outcomes",
        "arena_scores",
        "arena_runs",
        "arena_cases",
        "arena_campaign_state_events",
        "arena_campaigns",
    ):
        op.drop_table(table)
