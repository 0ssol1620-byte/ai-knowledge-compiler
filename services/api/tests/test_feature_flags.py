from __future__ import annotations

import uuid

import pytest
from akc_api.feature_flags import cohort_enabled, conditions_match, feature_enabled
from akc_api.models import Base, FeatureFlag, Tenant
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.parametrize("percent", [1, 5, 20, 50, 99])
def test_feature_cohorts_are_stable_for_a_tenant(percent: int) -> None:
    tenant_id = uuid.uuid4()
    first = cohort_enabled(
        tenant_id=tenant_id,
        key="ontology_export",
        enabled=True,
        percent=percent,
    )
    assert all(
        cohort_enabled(
            tenant_id=tenant_id,
            key="ontology_export",
            enabled=True,
            percent=percent,
        )
        is first
        for _ in range(20)
    )
    assert (
        cohort_enabled(
            tenant_id=tenant_id,
            key="ontology_export",
            enabled=False,
            percent=100,
        )
        is False
    )


def test_zero_percent_reaches_nobody() -> None:
    """0 is the first rung of the rollout ladder, not a synonym for 100.

    `cohort_enabled` folded 0 in with 100 and returned True for both, so an
    enabled flag at zero percent opened to the whole tenant. The v4 router
    starts shadow rollout at 0 precisely so that nothing is routed yet, which
    made the one setting that exists to be safe the one that was not. The
    column defaults to 0, so every freshly created enabled row was affected.
    """

    key = "V4_SHADOW_ROUTER"
    for _ in range(200):
        assert (
            cohort_enabled(
                tenant_id=uuid.uuid4(),
                key=key,
                enabled=True,
                percent=0,
            )
            is False
        )


@pytest.mark.parametrize("percent", [0, 5, 25, 50, 100])
def test_rollout_ladder_is_monotonic(percent: int) -> None:
    """Each rung admits at least as many subjects as the rung below it.

    Sampled over a fixed subject set rather than asserted per subject: the
    bucket is a hash, so the guarantee is that widening the percentage never
    withdraws a subject that a narrower one admitted.
    """

    tenant_id = uuid.uuid4()
    subjects = [uuid.uuid4() for _ in range(400)]
    key = "V4_SHADOW_ROUTER"

    def admitted(at: int) -> set[uuid.UUID]:
        return {
            subject
            for subject in subjects
            if cohort_enabled(
                tenant_id=tenant_id,
                subject_id=subject,
                key=key,
                enabled=True,
                percent=at,
            )
        }

    ladder = [0, 5, 25, 50, 100]
    below = ladder[: ladder.index(percent)]
    here = admitted(percent)
    for lower in below:
        assert admitted(lower) <= here, f"{lower}% admitted a subject {percent}% did not"
    if percent == 0:
        assert here == set()
    if percent == 100:
        assert here == set(subjects)


@pytest.mark.parametrize("percent", [-1, 101, 1000])
def test_out_of_range_percent_does_not_widen_the_cohort(percent: int) -> None:
    """The column has a 0..100 constraint; the resolver must not depend on it.

    A negative percentage reaches nobody and an over-100 one reaches everyone,
    rather than falling through the bucket comparison to an arbitrary answer.
    """

    result = cohort_enabled(
        tenant_id=uuid.uuid4(),
        key="V4_SHADOW_ROUTER",
        enabled=True,
        percent=percent,
    )
    assert result is (percent > 100)


def test_feature_conditions_are_bounded_and_fail_closed() -> None:
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    conditions = {
        "tenant_ids": [str(tenant_id)],
        "user_ids": [str(user_id)],
        "document_types": ["PDF", "docx"],
    }
    assert conditions_match(
        conditions,
        tenant_id=tenant_id,
        user_id=user_id,
        document_type="pdf",
    )
    assert not conditions_match(
        conditions,
        tenant_id=tenant_id,
        user_id=uuid.uuid4(),
        document_type="pdf",
    )
    assert not conditions_match(
        conditions,
        tenant_id=tenant_id,
        user_id=user_id,
        document_type="xlsx",
    )
    assert not conditions_match(
        {"unknown_condition": True},
        tenant_id=tenant_id,
        user_id=user_id,
        document_type="pdf",
    )
    assert not conditions_match(
        {"user_ids": "not-a-list"},
        tenant_id=tenant_id,
        user_id=user_id,
    )


async def test_tenant_feature_flag_overrides_global_default(tmp_path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'feature-flags.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    async with sessions.begin() as session:
        session.add(Tenant(id=tenant_id, slug="feature-tenant", name="Feature tenant"))
        session.add_all(
            [
                FeatureFlag(
                    tenant_id=None,
                    key="ontology_export",
                    enabled=True,
                    rollout_percent=0,
                ),
                FeatureFlag(
                    tenant_id=tenant_id,
                    key="ontology_export",
                    enabled=False,
                    rollout_percent=0,
                ),
            ]
        )
    async with sessions() as session:
        assert (
            await feature_enabled(
                session,
                tenant_id=tenant_id,
                key="ontology_export",
            )
            is False
        )
        assert (
            await feature_enabled(
                session,
                tenant_id=tenant_id,
                key="existing_vault_merge",
            )
            is False
        )
    await engine.dispose()


async def test_feature_flag_supports_user_and_document_type_rollout(tmp_path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'conditional-flags.db').as_posix()}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    async with sessions.begin() as session:
        session.add(Tenant(id=tenant_id, slug="conditional", name="Conditional"))
        session.add(
            FeatureFlag(
                tenant_id=tenant_id,
                key="chart_description",
                enabled=True,
                rollout_percent=100,
                conditions={
                    "user_ids": [str(user_id)],
                    "document_types": ["pdf"],
                },
            )
        )
    async with sessions() as session:
        assert await feature_enabled(
            session,
            tenant_id=tenant_id,
            key="chart_description",
            user_id=user_id,
            document_type="PDF",
        )
        assert not await feature_enabled(
            session,
            tenant_id=tenant_id,
            key="chart_description",
            user_id=uuid.uuid4(),
            document_type="pdf",
        )
        assert not await feature_enabled(
            session,
            tenant_id=tenant_id,
            key="chart_description",
            user_id=user_id,
            document_type="pptx",
        )
    await engine.dispose()
