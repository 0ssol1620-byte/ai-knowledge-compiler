"""Add immutable page attempts and append-only transition evidence.

Revision ID: 0013_page_attempts
Revises: 0012_team_collaboration
Create Date: 2026-07-30
"""

from __future__ import annotations

from akc_api.models import PageAttempt, PageAttemptTransitionEvent
from alembic import op
from sqlalchemy import inspect

revision = "0013_page_attempts"
down_revision = "0012_team_collaboration"
branch_labels = None
depends_on = None

ANALYSIS_ROLE = "akc_analysis_worker"
DISPATCH_ROLE = "akc_dispatch"
DELETION_ROLE = "akc_deletion_worker"

_TENANT_TABLES = (
    "page_attempts",
    "page_attempt_transition_events",
)


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _create_tables() -> None:
    bind = op.get_bind()
    if "page_attempts" not in _tables():
        PageAttempt.__table__.create(bind=bind)
    if "page_attempt_transition_events" not in _tables():
        PageAttemptTransitionEvent.__table__.create(bind=bind)


def _enable_rls_and_guards() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in _TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"'
        )
        op.execute(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            "USING (tenant_id = "
            "NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = "
            "NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION akc_page_attempt_immutable_guard()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status IN ('COMPLETED', 'NEEDS_REVIEW', 'FAILED') THEN
                RAISE EXCEPTION 'terminal page attempt is immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
               OR NEW.page_id IS DISTINCT FROM OLD.page_id
               OR NEW.job_id IS DISTINCT FROM OLD.job_id
               OR NEW.analysis_task_id IS DISTINCT FROM OLD.analysis_task_id
               OR NEW.attempt_number IS DISTINCT FROM OLD.attempt_number
               OR NEW.trigger IS DISTINCT FROM OLD.trigger
               OR NEW.route IS DISTINCT FROM OLD.route
               OR NEW.route_profile IS DISTINCT FROM OLD.route_profile
               OR NEW.route_policy_version IS DISTINCT FROM OLD.route_policy_version
               OR NEW.max_attempts IS DISTINCT FROM OLD.max_attempts
            THEN
                RAISE EXCEPTION 'page attempt identity and routing are immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS page_attempt_immutable_guard ON page_attempts"
    )
    op.execute(
        """
        CREATE TRIGGER page_attempt_immutable_guard
        BEFORE UPDATE ON page_attempts
        FOR EACH ROW EXECUTE FUNCTION akc_page_attempt_immutable_guard()
        """
    )
    op.execute(
        "REVOKE UPDATE, DELETE ON page_attempt_transition_events FROM PUBLIC"
    )


def _grant_worker_access() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"""
        GRANT SELECT ON TABLE
            feature_flags,
            model_registry,
            page_attempts,
            page_attempt_transition_events
        TO {ANALYSIS_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT INSERT ON TABLE
            page_attempts,
            page_attempt_transition_events
        TO {ANALYSIS_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            provider_invocation_id, status, quality_vector, quality_findings,
            quality_evaluation, escalation_decision, event_sequence,
            completed_at, updated_at
        ) ON TABLE page_attempts TO {ANALYSIS_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT SELECT ON TABLE
            tenants,
            projects,
            source_files,
            feature_flags,
            model_registry,
            page_attempts,
            page_attempt_transition_events
        TO {DISPATCH_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT INSERT ON TABLE
            page_attempts,
            page_attempt_transition_events
        TO {DISPATCH_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT UPDATE (
            provider_invocation_id, status, quality_vector, quality_findings,
            quality_evaluation, escalation_decision, event_sequence,
            completed_at, updated_at
        ) ON TABLE page_attempts TO {DISPATCH_ROLE}
        """
    )
    op.execute(
        f"""
        GRANT SELECT ON TABLE
            page_attempts,
            page_attempt_transition_events
        TO {DELETION_ROLE}
        """
    )


def upgrade() -> None:
    _create_tables()
    _enable_rls_and_guards()
    _grant_worker_access()


def downgrade() -> None:
    bind = op.get_bind()
    tables = _tables()
    if bind.dialect.name == "postgresql":
        for role in (ANALYSIS_ROLE, DISPATCH_ROLE, DELETION_ROLE):
            for table in reversed(_TENANT_TABLES):
                if table in tables:
                    op.execute(
                        f"REVOKE ALL PRIVILEGES ON TABLE {table} FROM {role}"
                    )
        for table in (
            "model_registry",
            "feature_flags",
            "source_files",
            "projects",
            "tenants",
        ):
            op.execute(
                f"REVOKE ALL PRIVILEGES ON TABLE {table} FROM {DISPATCH_ROLE}"
            )
        for table in ("model_registry", "feature_flags"):
            op.execute(
                f"REVOKE ALL PRIVILEGES ON TABLE {table} FROM {ANALYSIS_ROLE}"
            )
        op.execute(
            "DROP TRIGGER IF EXISTS page_attempt_immutable_guard ON page_attempts"
        )
        op.execute("DROP FUNCTION IF EXISTS akc_page_attempt_immutable_guard()")
        for table in reversed(_TENANT_TABLES):
            if table in tables:
                op.execute(
                    f'DROP POLICY IF EXISTS "{table}_tenant_isolation" '
                    f'ON "{table}"'
                )
    if "page_attempt_transition_events" in tables:
        PageAttemptTransitionEvent.__table__.drop(bind=bind)
    if "page_attempts" in tables:
        PageAttempt.__table__.drop(bind=bind)
