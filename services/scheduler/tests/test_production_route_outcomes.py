"""Database evidence for scheduler production route outcome persistence."""

from __future__ import annotations

import uuid
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from akc_api.arena_models import ProductionRouteOutcome
from akc_api.arena_repository import ArenaConflict
from akc_api.database import Database
from akc_api.models import Collection, ModelRegistry, ProcessingJob, Project, Tenant, User
from akc_api.settings import Settings
from akc_parallel_runtime import (
    AuthorizedRouteDecision,
    QualityEstimate,
    RecipeProfile,
    RouteCandidate,
    RouteDecision,
    RouteTier,
    RoutingAuthorityGrant,
    RoutingAuthorityMode,
    WorkerSnapshot,
    WorkerState,
)
from akc_scheduler.production_route_outcomes import (
    ProductionRouteOutcomeBindingError,
    TerminalProviderRouteEvidence,
    persist_terminal_production_route_outcome,
)
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

SHA_A = "a" * 64
SHA_B = "b" * 64


@pytest.fixture
def migrated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Database:
    database_path = tmp_path / "production-route-outcomes.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("AKC_DATABASE_URL", database_url)
    config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    command.upgrade(config, "head")
    return Database(Settings(database_url=database_url))


async def _seed_workspace(
    database: Database,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    processing_job_id = uuid.uuid4()
    user_id = uuid.uuid4()
    model_registry_id = uuid.uuid4()
    async with database.sessions() as session:
        session.add(Tenant(id=tenant_id, slug=f"tenant-{tenant_id.hex}", name="Tenant"))
        session.add(
            User(
                id=user_id,
                email=f"{user_id.hex}@example.test",
                password_hash="test-only-hash",  # noqa: S106
                display_name="Operator",
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
                name="Collection",
                status="PROCESSING",
                created_by=user_id,
            )
        )
        session.add(
            ProcessingJob(
                id=processing_job_id,
                tenant_id=tenant_id,
                project_id=workspace_id,
                document_id=None,
                job_type="parallel_v6",
                status="running",
                requested_options={"collection_id": str(collection_id)},
                progress={},
            )
        )
        session.add(
            ModelRegistry(
                id=model_registry_id,
                endpoint="provider",
                model_id="provider/model",
                revision="provider/model@2026-09-12",
                runtime_image_digest="sha256:" + SHA_A,
                adapter_version="adapter-v1",
                policy_version="deterministic-router-v1",
                benchmark_report="benchmark/report.json",
            )
        )
        await session.commit()
    return tenant_id, workspace_id, collection_id, processing_job_id, model_registry_id


def _authorized_decision() -> AuthorizedRouteDecision:
    recipe = RecipeProfile(
        recipe_id="native-provider",
        model_revision="provider/model@2026-09-12",
        runtime_image_digest="sha256:" + SHA_A,
        tier=RouteTier.NATIVE,
        capabilities=frozenset({"standard"}),
        supported_languages=frozenset({"ko"}),
        independent_family="native-provider",
    )
    worker = WorkerSnapshot(
        worker_id="worker-native-provider",
        model_revision=recipe.model_revision,
        runtime_image_digest=recipe.runtime_image_digest,
        state=WorkerState.HEALTHY,
        capabilities=recipe.capabilities,
        warm=True,
        cached_models=frozenset({recipe.model_revision}),
        estimated_available_at=0,
        semantic_score=99,
    )
    estimate = QualityEstimate(
        pass_hard_gate=0.99,
        numeric_exact=0.99,
        row_complete=0.99,
        repetition_probability=0.001,
        timeout_probability=0.001,
        oom_probability=0.001,
        expected_latency_seconds=1,
        expected_cost=0.001,
    )
    return AuthorizedRouteDecision(
        authority=RoutingAuthorityGrant(
            requested_mode=RoutingAuthorityMode.DETERMINISTIC,
            effective_mode=RoutingAuthorityMode.DETERMINISTIC,
            reason_codes=(),
        ),
        executable=RouteDecision(
            primary=RouteCandidate(
                recipe=recipe,
                worker=worker,
                estimate=estimate,
                objective_score=0,
            ),
            secondary=None,
            speculative=False,
            reason_codes=("native_first",),
            policy_version="deterministic-router-v1",
        ),
        counterfactual=None,
    )


def _terminal(
    *,
    collection_id: uuid.UUID,
    processing_job_id: uuid.UUID,
    model_registry_id: uuid.UUID,
) -> TerminalProviderRouteEvidence:
    return TerminalProviderRouteEvidence(
        outcome_id=uuid.uuid4(),
        collection_id=collection_id,
        processing_job_id=processing_job_id,
        shard_id="shard-1",
        idempotency_key="job-1:shard-1:provider-terminal",
        selected_recipe_id="native-provider",
        selected_worker_id="worker-native-provider",
        selected_model_revision="provider/model@2026-09-12",
        runtime_image_digest="sha256:" + SHA_A,
        permission_snapshot_sha256=SHA_A,
        route_receipt_sha256=SHA_B,
        outcome_status="EXECUTED",
        executable=True,
        trusted=True,
        latency_ms=91,
        actual_cost_usd=Decimal("0.0004000000"),
        selected_model_registry_id=model_registry_id,
    )


@pytest.mark.asyncio
async def test_terminal_route_outcome_is_exact_idempotent_and_not_research_eligible(
    migrated_database: Database,
) -> None:
    database = migrated_database
    (
        tenant_id,
        workspace_id,
        collection_id,
        processing_job_id,
        model_registry_id,
    ) = await _seed_workspace(database)
    decision = _authorized_decision()
    terminal = _terminal(
        collection_id=collection_id,
        processing_job_id=processing_job_id,
        model_registry_id=model_registry_id,
    )

    async with database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionRouteOutcome)) == 0
        outcome = await persist_terminal_production_route_outcome(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            decision=decision,
            terminal=terminal,
        )
        assert outcome.selected_path == "native-provider:worker-native-provider"
        assert outcome.selected_model_registry_id == model_registry_id
        assert outcome.trusted is True
        assert outcome.latency_ms == 91
        assert outcome.actual_cost_usd == Decimal("0.0004000000")
        assert outcome.research_use_allowed is False
        assert not hasattr(outcome, "arena_case_id")
        await session.commit()

    async with database.sessions() as session:
        replay = await persist_terminal_production_route_outcome(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            decision=decision,
            terminal=terminal,
        )
        assert replay.id == terminal.outcome_id
        assert await session.scalar(select(func.count()).select_from(ProductionRouteOutcome)) == 1

        with pytest.raises(ArenaConflict, match="idempotency key was reused"):
            await persist_terminal_production_route_outcome(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                decision=decision,
                terminal=replace(terminal, latency_ms=92),
            )
        await session.rollback()
    await database.dispose()


@pytest.mark.asyncio
async def test_terminal_provider_identity_must_match_authorized_route(
    migrated_database: Database,
) -> None:
    database = migrated_database
    (
        tenant_id,
        workspace_id,
        collection_id,
        processing_job_id,
        model_registry_id,
    ) = await _seed_workspace(database)
    terminal = replace(
        _terminal(
            collection_id=collection_id,
            processing_job_id=processing_job_id,
            model_registry_id=model_registry_id,
        ),
        selected_model_revision="provider/model@other",
    )

    async with database.sessions() as session:
        with pytest.raises(ProductionRouteOutcomeBindingError, match="identity differs"):
            await persist_terminal_production_route_outcome(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                decision=_authorized_decision(),
                terminal=terminal,
            )
        assert await session.scalar(select(func.count()).select_from(ProductionRouteOutcome)) == 0
    await database.dispose()
