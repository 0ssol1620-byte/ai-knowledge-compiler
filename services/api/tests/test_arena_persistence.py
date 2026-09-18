"""Executable evidence for Arena identity, lifecycle, and privacy boundaries."""

from __future__ import annotations

import uuid
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from akc_api.arena_models import (
    ArenaCampaignStateEvent,
    ArenaCase,
    ArenaRun,
    ArenaScore,
    ProductionRouteOutcome,
)
from akc_api.arena_repository import (
    ArenaCaseSpec,
    ArenaConflict,
    ArenaPrivacyBoundaryError,
    ArenaRunOutcome,
    ArenaRunSpec,
    ArenaScoreSpec,
    ArenaTransitionError,
    ProductionRouteOutcomeSpec,
    add_case,
    complete_run,
    create_campaign,
    finish_campaign,
    freeze_campaign,
    record_production_route_outcome,
    record_score,
    start_campaign,
    start_run,
)
from akc_api.database import Database
from akc_api.models import Collection, ModelRegistry, ProcessingJob, Project, Tenant, User
from akc_api.settings import Settings
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


@pytest.fixture
def migrated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Database:
    database_path = tmp_path / "arena.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("AKC_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    command.upgrade(config, "head")
    return Database(Settings(database_url=database_url))


async def _seed_authority(
    database: Database,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    processing_job_id = uuid.uuid4()
    model_id = uuid.uuid4()
    async with database.sessions() as session:
        session.add(Tenant(id=tenant_id, slug=f"tenant-{tenant_id.hex}", name="Arena Tenant"))
        session.add(
            User(
                id=user_id,
                email=f"{user_id.hex}@example.test",
                password_hash="test-only-hash",  # noqa: S106
                display_name="Arena Operator",
            )
        )
        await session.flush()
        session.add(
            Project(
                id=workspace_id,
                tenant_id=tenant_id,
                name="Workspace",
                created_by=user_id,
            )
        )
        await session.flush()
        session.add(
            Collection(
                id=collection_id,
                tenant_id=tenant_id,
                project_id=workspace_id,
                name="Arena-bound production collection",
                status="PROCESSING",
                created_by=user_id,
            )
        )
        session.add(
            ProcessingJob(
                id=processing_job_id,
                tenant_id=tenant_id,
                project_id=workspace_id,
                job_type="collection_processing",
                status="running",
                requested_options={"collection_id": str(collection_id)},
            )
        )
        session.add(
            ModelRegistry(
                id=model_id,
                endpoint="arena-provider",
                model_id="provider/model",
                revision="provider/model@2026-09-12",
                runtime_image_digest="sha256:" + SHA_A,
                adapter_version="adapter-v1",
                policy_version="policy-v1",
                benchmark_report="research/arena/report.json",
            )
        )
        await session.commit()
    return tenant_id, workspace_id, collection_id, processing_job_id, model_id


def _case(
    campaign_id: uuid.UUID, *, split: str = "EVAL", family: str = "family-eval"
) -> ArenaCaseSpec:
    return ArenaCaseSpec(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        document_family_id=family,
        page_or_document_id=f"page-{uuid.uuid4().hex}",
        split=split,  # type: ignore[arg-type]
        origin="OMNIDOC",
        slice_labels=("TABLE_HEAVY", "FINANCIAL", "TABLE_HEAVY"),
        risk_class="HIGH",
        source_artifact_ref="arena/public/source/page-1.png",
        source_artifact_sha256=SHA_C,
        truth_ref="arena/public/truth/page-1.json",
        license_ref="docs/licenses/omnidocbench.txt",
    )


def _run(campaign_id: uuid.UUID, case_id: uuid.UUID, model_id: uuid.UUID) -> ArenaRunSpec:
    return ArenaRunSpec(
        id=uuid.uuid4(),
        campaign_id=campaign_id,
        case_id=case_id,
        model_registry_id=model_id,
        idempotency_key="dispatch-1",
        exact_model_id="provider/model",
        exact_model_revision="provider/model@2026-09-12",
        input_track="STANDARD_IMAGE",
        prompt_track="STANDARD",
        batch_mode=True,
        prompt_sha256=SHA_A,
        schema_sha256=SHA_B,
        settings_sha256=SHA_C,
        input_artifact_ref="arena/public/render/page-1.png",
        input_artifact_sha256=SHA_D,
        price_snapshot_ref="arena/receipts/prices/provider-model.json",
        price_snapshot_sha256=SHA_E,
    )


@pytest.mark.asyncio
async def test_campaign_run_and_score_are_complete_idempotent_and_sealed(
    migrated_database: Database,
) -> None:
    database = migrated_database
    _, _, _, _, model_id = await _seed_authority(database)
    campaign_id = uuid.uuid4()
    case_spec = _case(campaign_id)
    run_spec = _run(campaign_id, case_spec.id, model_id)
    outcome = ArenaRunOutcome(
        status="SUCCESS",
        latency_ms=812,
        input_units={"pages": 1, "tokens": 1200},
        output_units={"tokens": 430},
        actual_cost_usd=Decimal("0.0123000000"),
        terminal_receipt_sha256=SHA_F,
        raw_output_artifact_ref="arena/raw/run-1.json",
        raw_output_sha256=SHA_A,
        normalized_output_artifact_ref="arena/normalized/run-1.json",
        normalized_output_sha256=SHA_B,
    )
    score_spec = ArenaScoreSpec(
        evaluator_id="omnidoc-teds",
        evaluator_revision="official@2026-09-12",
        metric_name="teds",
        value=0.94,
        evaluator_artifact_ref="arena/evaluators/omnidoc.json",
        evaluator_artifact_sha256=SHA_C,
        receipt_ref="arena/receipts/run-1-teds.json",
        receipt_sha256=SHA_D,
    )
    async with database.sessions() as session:
        campaign = await create_campaign(
            session,
            campaign_id=campaign_id,
            name="Arena v1",
            corpus_manifest_sha256=SHA_A,
            protocol_version="arena-v1",
            protocol_sha256=SHA_B,
        )
        assert await create_campaign(
            session,
            campaign_id=campaign_id,
            name="Arena v1",
            corpus_manifest_sha256=SHA_A,
            protocol_version="arena-v1",
            protocol_sha256=SHA_B,
        ) is campaign
        case = await add_case(session, case_spec)
        assert case.slice_labels == ["FINANCIAL", "TABLE_HEAVY"]
        await freeze_campaign(
            session,
            campaign_id=campaign_id,
            expected_manifest_sha256=SHA_A,
            transition_receipt_sha256=SHA_C,
        )
        with pytest.raises(ArenaTransitionError, match="immutable after freeze"):
            await add_case(session, _case(campaign_id))
        await start_campaign(
            session, campaign_id=campaign_id, transition_receipt_sha256=SHA_D
        )
        run = await start_run(session, run_spec)
        assert await start_run(session, run_spec) is run
        await complete_run(session, run_id=run.id, outcome=outcome)
        assert await complete_run(session, run_id=run.id, outcome=outcome) is run
        with pytest.raises(ArenaConflict, match="outcome is immutable"):
            await complete_run(
                session,
                run_id=run.id,
                outcome=replace(outcome, actual_cost_usd=Decimal("0.9990000000")),
            )
        score = await record_score(session, run_id=run.id, score=score_spec)
        assert await record_score(session, run_id=run.id, score=score_spec) is score
        with pytest.raises(ArenaConflict, match="append-only"):
            await record_score(session, run_id=run.id, score=replace(score_spec, value=0.12))
        campaign = await finish_campaign(
            session,
            campaign_id=campaign_id,
            status="FINALIZED",
            terminal_receipt_sha256=SHA_E,
        )
        assert campaign.outcome_counts == {"SUCCESS": 1}
        events = list(
            (
                await session.scalars(
                    select(ArenaCampaignStateEvent)
                    .where(ArenaCampaignStateEvent.campaign_id == campaign_id)
                    .order_by(ArenaCampaignStateEvent.sequence)
                )
            ).all()
        )
        assert [(event.from_status, event.to_status) for event in events] == [
            (None, "DRAFT"),
            ("DRAFT", "FROZEN"),
            ("FROZEN", "RUNNING"),
            ("RUNNING", "FINALIZED"),
        ]
        await session.commit()
    await database.dispose()


@pytest.mark.asyncio
async def test_freeze_rejects_calibration_family_leakage(
    migrated_database: Database,
) -> None:
    database = migrated_database
    campaign_id = uuid.uuid4()
    async with database.sessions() as session:
        await create_campaign(
            session,
            campaign_id=campaign_id,
            name="Leaky Arena",
            corpus_manifest_sha256=SHA_A,
            protocol_version="arena-v1",
            protocol_sha256=SHA_B,
        )
        await add_case(session, _case(campaign_id, split="CALIBRATION", family="same-family"))
        await add_case(session, _case(campaign_id, split="ROUTER_HOLDOUT", family="same-family"))
        with pytest.raises(ArenaConflict, match="families overlap"):
            await freeze_campaign(
                session,
                campaign_id=campaign_id,
                expected_manifest_sha256=SHA_A,
                transition_receipt_sha256=SHA_C,
            )
        await session.rollback()
    await database.dispose()


@pytest.mark.asyncio
async def test_run_rejects_model_registry_identity_drift(
    migrated_database: Database,
) -> None:
    database = migrated_database
    _, _, _, _, model_id = await _seed_authority(database)
    campaign_id = uuid.uuid4()
    case_spec = _case(campaign_id)
    async with database.sessions() as session:
        await create_campaign(
            session,
            campaign_id=campaign_id,
            name="Identity Arena",
            corpus_manifest_sha256=SHA_A,
            protocol_version="arena-v1",
            protocol_sha256=SHA_B,
        )
        await add_case(session, case_spec)
        await freeze_campaign(
            session,
            campaign_id=campaign_id,
            expected_manifest_sha256=SHA_A,
            transition_receipt_sha256=SHA_C,
        )
        drifted = _run(campaign_id, case_spec.id, model_id)
        drifted = replace(drifted, exact_model_revision="provider/model@changed")
        with pytest.raises(ArenaConflict, match="does not match"):
            await start_run(session, drifted)
        await session.rollback()
    await database.dispose()


@pytest.mark.asyncio
async def test_production_outcome_is_tenant_bound_and_never_research_eligible(
    migrated_database: Database,
) -> None:
    database = migrated_database
    tenant_id, workspace_id, collection_id, processing_job_id, model_id = (
        await _seed_authority(database)
    )
    spec = ProductionRouteOutcomeSpec(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        collection_id=collection_id,
        processing_job_id=processing_job_id,
        shard_id="shard-0001",
        idempotency_key="route-request-1",
        requested_mode="adaptive",
        effective_mode="deterministic",
        decision_kind="DETERMINISTIC",
        executable=True,
        outcome_status="EXECUTED",
        selected_path="native-cheap",
        selected_model_registry_id=model_id,
        policy_version="policy-v1",
        policy_sha256=SHA_A,
        authority_envelope_sha256=SHA_B,
        permission_snapshot_sha256=SHA_C,
        route_receipt_sha256=SHA_D,
        fail_closed_reason_codes=(),
        shadow_counterfactual={"decision": "adaptive-shadow", "executable": False},
        trusted=True,
        latency_ms=92,
        actual_cost_usd=Decimal("0.0004000000"),
    )
    async with database.sessions() as session:
        outcome = await record_production_route_outcome(session, spec)
        assert outcome.research_use_allowed is False
        assert await record_production_route_outcome(session, spec) is outcome
        assert not hasattr(outcome, "arena_case_id")
        foreign_tenant = replace(spec, id=uuid.uuid4(), tenant_id=uuid.uuid4())
        with pytest.raises(ArenaPrivacyBoundaryError, match="outside"):
            await record_production_route_outcome(session, foreign_tenant)
        await session.commit()
    await database.dispose()


@pytest.mark.asyncio
async def test_database_guards_reject_rewriting_evidence(
    migrated_database: Database,
) -> None:
    database = migrated_database
    campaign_id = uuid.uuid4()
    case_spec = _case(campaign_id)
    async with database.sessions() as session:
        await create_campaign(
            session,
            campaign_id=campaign_id,
            name="Guarded Arena",
            corpus_manifest_sha256=SHA_A,
            protocol_version="arena-v1",
            protocol_sha256=SHA_B,
        )
        await add_case(session, case_spec)
        await session.commit()
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(
                text("UPDATE arena_cases SET truth_ref = 'rewritten' WHERE id = :id"),
                {"id": case_spec.id.hex},
            )
        await session.rollback()
        with pytest.raises(DBAPIError, match="cannot be deleted"):
            await session.execute(
                text("DELETE FROM arena_campaigns WHERE id = :id"),
                {"id": campaign_id.hex},
            )
        await session.rollback()
    await database.dispose()


def test_schema_has_no_customer_to_research_bridge() -> None:
    assert "tenant_id" not in ArenaCase.__table__.columns
    assert "workspace_id" not in ArenaCase.__table__.columns
    assert "arena_case_id" not in ProductionRouteOutcome.__table__.columns
    assert "source_artifact_ref" not in ProductionRouteOutcome.__table__.columns
    assert ProductionRouteOutcome.__table__.c.research_use_allowed.nullable is False
    assert ArenaRun.__table__.c.model_registry_id.nullable is False
    assert ArenaScore.__table__.c.evaluator_revision.primary_key is True


def test_postgres_production_outcome_acl_keeps_read_and_write_planes_distinct() -> None:
    migration = (
        Path(__file__).resolve().parents[3]
        / "migrations"
        / "versions"
        / "0041_arena_persistence.py"
    ).read_text(encoding="utf-8")

    assert (
        "GRANT SELECT, INSERT ON production_route_outcomes TO akc_scheduler" in migration
    )
    assert "GRANT SELECT ON production_route_outcomes TO akc_api_plane" in migration
    assert (
        "GRANT SELECT, INSERT ON production_route_outcomes TO akc_scheduler, akc_api_plane"
        not in migration
    )
    assert "AS RESTRICTIVE TO PUBLIC" in migration
    assert "TO akc_scheduler, akc_api_plane" in migration
    assert "current_setting('app.tenant_id', true)" in migration
    assert "ALTER ROLE akc_scheduler" not in migration


def test_arena_migration_round_trip(migrated_database: Database) -> None:
    config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    command.downgrade(config, "0037_gpu_post_claim_authorization")
    command.upgrade(config, "head")
    command.check(config)
