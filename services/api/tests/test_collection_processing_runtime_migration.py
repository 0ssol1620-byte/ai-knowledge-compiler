"""Contract evidence for the collection processing runtime migration."""

from __future__ import annotations

import importlib
from typing import Any

from akc_api import models as _models  # noqa: F401
from akc_api.collection_schemas import CollectionEventResponse
from akc_api.database import Base
from akc_api.models import ArchitecturePlan, Collection, CollectionProcessingTaskBinding
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

MIGRATION = importlib.import_module("migrations.versions.0025_collection_processing_runtime")


def _operations(connection: Any) -> Operations:
    return Operations(MigrationContext.configure(connection))


def test_collection_runtime_orm_contract_is_not_cross_wired() -> None:
    architecture_columns = set(ArchitecturePlan.__table__.c.keys())
    collection_columns = set(Collection.__table__.c.keys())
    binding_columns = set(CollectionProcessingTaskBinding.__table__.c.keys())

    assert {
        "processing_job_id",
        "plan_version",
        "input_integrity_sha256",
        "created_at",
    } <= architecture_columns
    assert {
        "processing_job_id",
        "plan_version",
        "input_integrity_sha256",
    }.isdisjoint(collection_columns)
    assert {
        "billing_disposition",
        "billing_owner_job_id",
        "billing_basis_sha256",
        "status",
        "settled_at",
    } <= binding_columns

    architecture_constraint_names = {
        constraint.name for constraint in ArchitecturePlan.__table__.constraints
    }
    assert "ck_architecture_plan_version" in architecture_constraint_names
    assert "ck_architecture_plan_status" in architecture_constraint_names
    binding_constraint_names = {
        constraint.name for constraint in CollectionProcessingTaskBinding.__table__.constraints
    }
    assert "ck_collection_processing_task_binding_status" in binding_constraint_names
    assert "ck_collection_processing_task_binding_billing" in binding_constraint_names
    assert "ck_collection_processing_task_binding_basis_sha" in binding_constraint_names

    schema = CollectionEventResponse.model_json_schema()
    assert "job_id" in schema["required"]
    assert {item.get("type") for item in schema["properties"]["job_id"]["anyOf"]} == {
        "string",
        "null",
    }


def test_collection_runtime_migration_sqlite_is_idempotent_on_current_schema(
    monkeypatch: Any,
) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        monkeypatch.setattr(MIGRATION, "op", _operations(connection))

        MIGRATION.upgrade()
        inspector = inspect(connection)
        binding_columns = {
            column["name"]
            for column in inspector.get_columns("collection_processing_task_bindings")
        }
        assert {
            "billing_disposition",
            "billing_owner_job_id",
            "billing_basis_sha256",
        } <= binding_columns
        checks = " ".join(
            str(row["sqltext"])
            for row in inspector.get_check_constraints("collection_processing_task_bindings")
        )
        assert "reuse_unbillable" in checks
        assert "paused" in checks

        for table in (
            "page_fingerprints",
            "preflight_feature_records",
            "estimate_samples",
        ):
            page_column = next(
                row for row in inspector.get_columns(table) if row["name"] == "page_id"
            )
            assert page_column["nullable"] is True
            page_fk = next(
                row
                for row in inspector.get_foreign_keys(table)
                if row["referred_table"] == "pages"
                and row["constrained_columns"] == ["tenant_id", "page_id"]
            )
            assert str(page_fk.get("options", {}).get("ondelete", "")).upper() == "SET NULL"

        assert MIGRATION.revision == "0025_collection_processing_runtime"
        assert MIGRATION.down_revision == "0024_production_hybrid_retrieval"


def test_collection_runtime_rls_contract_requires_tenant_and_project_membership() -> None:
    read = MIGRATION._project_access(write=False)
    write = MIGRATION._project_access(write=True)

    for clause in (read, write):
        assert "current_setting('app.tenant_id', true)" in clause
        assert "current_setting('app.user_id', true)" in clause
        assert "project_memberships" in clause
        assert "collection_scope.project_id" in clause
    assert "viewer" in read
    assert "viewer" not in write


def test_collection_runtime_sqlite_downgrade_preserves_rows_and_unrelated_fks(
    monkeypatch: Any,
) -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        for statement in (
            "CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY)",
            """
            CREATE TABLE processing_jobs (
                tenant_id VARCHAR(36) NOT NULL,
                id VARCHAR(36) NOT NULL,
                PRIMARY KEY (tenant_id, id)
            )
            """,
            """
            CREATE TABLE collection_events (
                id VARCHAR(36) PRIMARY KEY,
                tenant_id VARCHAR(36) NOT NULL,
                project_id VARCHAR(36) NOT NULL,
                job_id VARCHAR(36),
                sequence INTEGER NOT NULL,
                payload VARCHAR(100) NOT NULL,
                CONSTRAINT fk_collection_events_processing_job
                    FOREIGN KEY (tenant_id, job_id)
                    REFERENCES processing_jobs (tenant_id, id) ON DELETE SET NULL,
                CONSTRAINT fk_collection_events_project
                    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE architecture_plans (
                id VARCHAR(36) PRIMARY KEY,
                tenant_id VARCHAR(36) NOT NULL,
                processing_job_id VARCHAR(36),
                plan_json VARCHAR(100) NOT NULL,
                CONSTRAINT fk_architecture_plans_processing_job
                    FOREIGN KEY (tenant_id, processing_job_id)
                    REFERENCES processing_jobs (tenant_id, id) ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE estimate_runs (
                id VARCHAR(36) PRIMARY KEY,
                estimate_sha256 VARCHAR(64) NOT NULL,
                label VARCHAR(40) NOT NULL,
                CONSTRAINT ck_estimate_runs_estimate_sha
                    CHECK (length(estimate_sha256) = 64)
            )
            """,
            """
            CREATE TABLE estimate_samples (
                id VARCHAR(36) PRIMARY KEY,
                runtime_seconds NUMERIC(12, 6) NOT NULL,
                probe_revision VARCHAR(120) NOT NULL,
                probe_artifact_sha256 VARCHAR(64) NOT NULL,
                attestation_sha256 VARCHAR(64) NOT NULL,
                attestation VARCHAR(100) NOT NULL,
                attestation_key_id VARCHAR(160) NOT NULL,
                attestation_signature VARCHAR(4096) NOT NULL,
                sample_label VARCHAR(40) NOT NULL,
                CONSTRAINT ck_estimate_samples_attestation_hashes CHECK (
                    length(probe_artifact_sha256) = 64
                    AND length(attestation_sha256) = 64
                ),
                CONSTRAINT ck_estimate_samples_runtime CHECK (runtime_seconds > 0)
            )
            """,
            """
            CREATE TABLE outbox_events (
                id VARCHAR(36) PRIMARY KEY,
                available_at DATETIME NOT NULL,
                created_at DATETIME NOT NULL,
                published_at DATETIME,
                dead_lettered_at DATETIME,
                event_type VARCHAR(120) NOT NULL
            )
            """,
            "CREATE TABLE collection_processing_task_bindings (id VARCHAR(36) PRIMARY KEY)",
            "CREATE INDEX collection_events_job_idx "
            "ON collection_events (tenant_id, job_id, sequence)",
            """
            CREATE INDEX outbox_collection_finalizer_pending_idx
            ON outbox_events (available_at, created_at, id)
            WHERE published_at IS NULL AND dead_lettered_at IS NULL
              AND event_type = 'collection.semantic.compile.requested.v1'
            """,
            "INSERT INTO projects (id) VALUES ('project-1')",
            "INSERT INTO processing_jobs (tenant_id, id) VALUES ('tenant-1', 'job-1')",
            """
            INSERT INTO collection_events
                (id, tenant_id, project_id, job_id, sequence, payload)
            VALUES ('event-1', 'tenant-1', 'project-1', 'job-1', 1, 'retained')
            """,
            """
            INSERT INTO architecture_plans
                (id, tenant_id, processing_job_id, plan_json)
            VALUES ('plan-1', 'tenant-1', 'job-1', '{}')
            """,
            """
            INSERT INTO estimate_runs (id, estimate_sha256, label)
            VALUES (
                'run-1',
                'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                'retained'
            )
            """,
            """
            INSERT INTO estimate_samples (
                id, runtime_seconds, probe_revision, probe_artifact_sha256,
                attestation_sha256, attestation, attestation_key_id,
                attestation_signature, sample_label
            ) VALUES (
                'sample-1', 1.25, 'probe-v1',
                'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
                '{}', 'key-1', 'signature-1', 'retained'
            )
            """,
        ):
            connection.exec_driver_sql(statement)

        monkeypatch.setattr(MIGRATION, "op", _operations(connection))
        MIGRATION.downgrade()

        inspector = inspect(connection)
        assert "collection_processing_task_bindings" not in inspector.get_table_names()
        assert "outbox_collection_finalizer_pending_idx" not in {
            str(row["name"]) for row in inspector.get_indexes("outbox_events")
        }
        assert "job_id" not in {
            str(row["name"]) for row in inspector.get_columns("collection_events")
        }
        assert "processing_job_id" not in {
            str(row["name"]) for row in inspector.get_columns("architecture_plans")
        }
        assert "estimate_sha256" not in {
            str(row["name"]) for row in inspector.get_columns("estimate_runs")
        }
        assert {
            "probe_revision",
            "probe_artifact_sha256",
            "attestation_sha256",
            "attestation",
            "attestation_key_id",
            "attestation_signature",
        }.isdisjoint(
            {str(row["name"]) for row in inspector.get_columns("estimate_samples")}
        )
        assert any(
            row.get("referred_table") == "projects"
            and row.get("constrained_columns") == ["project_id"]
            for row in inspector.get_foreign_keys("collection_events")
        )
        assert connection.exec_driver_sql(
            "SELECT project_id, payload FROM collection_events WHERE id = 'event-1'"
        ).one() == ("project-1", "retained")
        assert connection.exec_driver_sql(
            "SELECT plan_json FROM architecture_plans WHERE id = 'plan-1'"
        ).scalar_one() == "{}"
        assert connection.exec_driver_sql(
            "SELECT label FROM estimate_runs WHERE id = 'run-1'"
        ).scalar_one() == "retained"
        assert connection.exec_driver_sql(
            "SELECT runtime_seconds, sample_label FROM estimate_samples "
            "WHERE id = 'sample-1'"
        ).one() == (1.25, "retained")
