"""Real async orchestration with synthetic providers; not OCR accuracy evidence."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from akc_router.document_execution import (
    DocumentSourceBinding,
    RegionWork,
    execute_document_text_plan,
)
from akc_router.evidence_execution import (
    IndependentTextWitness,
    RegionAttempt,
    RegionBinding,
    TextObservation,
    execute_text_region,
    text_digest,
)
from akc_router.execution_plan import (
    DeadlineClass,
    DependencyEdge,
    DependencyKind,
    DocumentExecutionPlan,
    ExecutionLane,
    ExecutionWave,
)
from akc_router.models import DataPolicy, ProcessingMode, Route
from akc_router.portfolio import build_portfolio

SHA = "sha256:" + "a" * 64
REP = "sha256:" + "b" * 64
SOURCE = DocumentSourceBinding("version-1", SHA, REP)
TEXT = "Revenue was -12.5 million USD in 2026. 한글 근거."
PORTFOLIO = build_portfolio({ExecutionLane.NATIVE: (Route.NATIVE, None)}, {})


def work(unit="r1", attempts=None, witness=True):
    binding = RegionBinding(SHA, REP, 0, unit, (10, 10, 900, 200))
    reference = TextObservation(binding, "trusted-source-reader", TEXT, text_digest(TEXT))
    return RegionWork(
        binding,
        IndependentTextWitness(reference, "source-record-1", True) if witness else None,
        attempts or (RegionAttempt(Route.NATIVE, "native-reader", 0.1, 1),),
    )


def plan(units=("r1",), *, waves=None, edges=(), budget=10, parallel=2, policy=None):
    return DocumentExecutionPlan(
        plan_id="test-plan-1",
        source_version_id="version-1",
        planner_revision="test-only",
        feature_manifest_sha256=SHA,
        portfolio_revision=PORTFOLIO.revision,
        data_policy=policy or DataPolicy(),
        deadline_class=DeadlineClass.STANDARD,
        cost_budget=budget,
        parallelism_budget=parallel,
        execution_waves=waves
        or (ExecutionWave(wave_index=0, lane=ExecutionLane.NATIVE, unit_ids=units),),
        dependency_edges=edges,
        predicted_p50=0,
        predicted_p95=0,
        predicted_verified_cost=0,
    )


async def native(binding):
    return TextObservation(binding, "native-reader", TEXT, text_digest(TEXT))


def execute(p=None, regions=None, providers=None, **kwargs):
    return execute_document_text_plan(
        plan=p or plan(),
        source=kwargs.pop("source", SOURCE),
        regions=regions or {"r1": work()},
        providers=providers or {Route.NATIVE: native},
        portfolio=kwargs.pop("portfolio", PORTFOLIO),
        qualified_routes=kwargs.pop("qualified_routes", frozenset(Route)),
        authorization_valid=kwargs.pop("authorization_valid", lambda: True),
        deadline_seconds=kwargs.pop("deadline_seconds", 5),
        **kwargs,
    )


def waves():
    return (
        ExecutionWave(wave_index=0, lane=ExecutionLane.NATIVE, unit_ids=("r1",)),
        ExecutionWave(wave_index=1, lane=ExecutionLane.NATIVE, unit_ids=("r2",)),
    )


def edge():
    return DependencyEdge(from_unit_id="r1", to_unit_id="r2", kind=DependencyKind.FOOTNOTE)


@pytest.mark.asyncio
async def test_executes_existing_plan_but_never_promotes_world():
    result = await execute()
    assert result.disposition == "verified_text_scope"
    assert result.regions["r1"].accepted.text == TEXT
    assert result.production_promotion is False
    assert result.verification_scope == "declared_text_regions_only"
    with pytest.raises(TypeError):
        result.regions["evil"] = result.regions["r1"]


@pytest.mark.asyncio
async def test_real_parallel_execution_is_bounded_by_plan():
    running, maximum = 0, 0
    both = asyncio.Event()

    async def provider(binding):
        nonlocal running, maximum
        running += 1
        maximum = max(maximum, running)
        if running == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 1)
        await asyncio.sleep(0)
        running -= 1
        return await native(binding)

    units = tuple(f"r{i}" for i in range(12))
    result = await execute(
        plan(units, parallel=2), {u: work(u) for u in units}, {Route.NATIVE: provider}
    )
    assert maximum == 2 and running == 0
    assert len(result.regions) == 12
    assert result.disposition == "verified_text_scope"


@pytest.mark.asyncio
async def test_provider_queue_capacity_is_separate_from_document_parallelism():
    running, maximum = 0, 0

    async def provider(binding):
        nonlocal running, maximum
        running += 1
        maximum = max(maximum, running)
        await asyncio.sleep(0)
        running -= 1
        return await native(binding)

    units = ("r1", "r2", "r3")
    await execute(
        plan(units, parallel=3),
        {u: work(u) for u in units},
        {Route.NATIVE: provider},
        route_concurrency={Route.NATIVE: 1},
    )
    assert maximum == 1


@pytest.mark.asyncio
async def test_recovery_and_primary_share_atomic_document_budget():
    calls = []

    async def wrong(binding):
        calls.append(binding.region_id)
        return TextObservation(binding, "native-reader", "12.5", text_digest("12.5"))

    async def alternate(binding):
        calls.append("alternate")
        return TextObservation(binding, "alternate-reader", TEXT, text_digest(TEXT))

    attempts = (
        RegionAttempt(Route.NATIVE, "native-reader", 0.1, 1),
        RegionAttempt(Route.PADDLE_VL, "alternate-reader", 0.1, 1),
    )
    units = ("r1", "r2", "r3")
    result = await execute(
        plan(units, budget=0.3),
        {u: work(u, attempts) for u in units},
        {Route.NATIVE: wrong, Route.PADDLE_VL: alternate},
    )
    assert result.reserved_cost <= 0.3
    assert len(calls) == 3
    assert len(result.regions) == 3
    assert any("DOCUMENT_BUDGET_REACHED" in r.reasons for r in result.regions.values())


@pytest.mark.asyncio
async def test_failed_upstream_blocks_dependent_execution_and_retains_row():
    calls = []

    async def provider(binding):
        calls.append(binding.region_id)
        return await native(binding)

    result = await execute(
        plan(waves=waves(), edges=(edge(),)),
        {"r1": work(witness=False), "r2": work("r2")},
        {Route.NATIVE: provider},
    )
    assert calls == ["r1"]
    assert result.regions["r2"].reasons == ("DEPENDENCY_NOT_VERIFIED",)
    assert result.disposition == "unresolved"


@pytest.mark.asyncio
async def test_completed_upstream_precedes_dependent_wave():
    order = []

    async def provider(binding):
        order.append(binding.region_id + ":start")
        await asyncio.sleep(0)
        order.append(binding.region_id + ":end")
        return await native(binding)

    await execute(
        plan(waves=waves(), edges=(edge(),)),
        {"r1": work(), "r2": work("r2")},
        {Route.NATIVE: provider},
    )
    assert order == ["r1:start", "r1:end", "r2:start", "r2:end"]


@pytest.mark.asyncio
async def test_same_wave_dependency_and_cycle_fail_before_provider():
    with pytest.raises(ValueError, match="DEPENDENCY_WAVE"):
        await execute(plan(("r1", "r2"), edges=(edge(),)), {"r1": work(), "r2": work("r2")})
    reverse = DependencyEdge(from_unit_id="r2", to_unit_id="r1", kind=DependencyKind.FOOTNOTE)
    with pytest.raises(ValueError, match="DEPENDENCY_WAVE"):
        await execute(
            plan(waves=waves(), edges=(edge(), reverse)), {"r1": work(), "r2": work("r2")}
        )


@pytest.mark.asyncio
async def test_dependency_outside_inventory_fails_before_work():
    with pytest.raises(ValueError, match="OUTSIDE_INVENTORY"):
        await execute(plan(edges=(edge(),)))


@pytest.mark.asyncio
async def test_duplicate_units_across_lanes_are_not_executed_twice():
    repeated = (
        ExecutionWave(wave_index=0, lane=ExecutionLane.NATIVE, unit_ids=("r1",)),
        ExecutionWave(wave_index=0, lane=ExecutionLane.FAST_VISUAL, unit_ids=("r1",)),
    )
    with pytest.raises(ValueError, match="UNIT_REPEATED"):
        await execute(plan(waves=repeated))


@pytest.mark.asyncio
async def test_unlisted_region_does_not_disappear_from_denominator():
    with pytest.raises(ValueError, match="INVENTORY_MISMATCH"):
        await execute(regions={"r1": work(), "r2": work("r2")})


@pytest.mark.asyncio
async def test_foreign_source_binding_refused_before_work():
    with pytest.raises(ValueError, match="PLAN_SOURCE"):
        await execute(source=replace(SOURCE, source_version_id="another"))
    with pytest.raises(ValueError, match="REGION_SOURCE"):
        await execute(source=replace(SOURCE, source_sha256=REP))


@pytest.mark.asyncio
async def test_unqualified_route_never_runs():
    with pytest.raises(ValueError, match="UNQUALIFIED"):
        await execute(qualified_routes=frozenset())


@pytest.mark.asyncio
async def test_changed_portfolio_revision_is_refused_before_execution():
    with pytest.raises(ValueError, match="PORTFOLIO_REVISION"):
        await execute(portfolio=replace(PORTFOLIO, revision="different-runtime-set"))


@pytest.mark.asyncio
async def test_primary_provider_must_match_the_declared_execution_lane():
    alternate = (RegionAttempt(Route.PADDLE_VL, "native-reader", 0.1, 1),)
    with pytest.raises(ValueError, match="PRIMARY_LANE_MISMATCH"):
        await execute(regions={"r1": work(attempts=alternate)}, providers={Route.PADDLE_VL: native})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options", [{}, {"mode": ProcessingMode.PRIVATE}, {"secret_detected": True}]
)
async def test_external_route_filtered_again_at_execution(options):
    attempt = (RegionAttempt(Route.MISTRAL_FALLBACK, "external", 0, 1),)
    policy = DataPolicy(external_api_allowed=bool(options))
    with pytest.raises(ValueError, match="UNPERMITTED"):
        await execute(
            plan(policy=policy),
            {"r1": work(attempts=attempt)},
            {Route.MISTRAL_FALLBACK: native},
            **options,
        )


@pytest.mark.asyncio
async def test_authority_revocation_during_provider_discards_accepted_text():
    allowed = True

    async def provider(binding):
        nonlocal allowed
        allowed = False
        return await native(binding)

    result = await execute(providers={Route.NATIVE: provider}, authorization_valid=lambda: allowed)
    assert result.regions["r1"].accepted is None
    assert result.disposition == "unresolved"
    assert result.reasons == ("EXECUTION_AUTHORIZATION_REVOKED",)


@pytest.mark.asyncio
async def test_authority_exception_is_safe_and_no_text_leaks():
    def authority():
        raise RuntimeError("sensitive source content")

    result = await execute(authorization_valid=authority)
    assert result.reserved_cost == 0
    assert "sensitive" not in repr(result)


@pytest.mark.asyncio
async def test_quarantine_stops_later_wave_and_withholds_prior_accepted_text():
    calls = []

    async def provider(binding):
        calls.append(binding.region_id)
        if binding.region_id == "r1":
            return TextObservation(
                replace(binding, representation_sha256=SHA),
                "native-reader",
                TEXT,
                text_digest(TEXT),
            )
        return await native(binding)

    result = await execute(
        plan(waves=waves()), {"r1": work(), "r2": work("r2")}, {Route.NATIVE: provider}
    )
    assert calls == ["r1"]
    assert result.disposition == "quarantined"
    assert all(r.accepted is None for r in result.regions.values())


@pytest.mark.asyncio
async def test_cancellation_drains_cooperative_providers():
    entered = asyncio.Event()
    stopped = asyncio.Event()

    async def provider(binding):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
        return await native(binding)

    task = asyncio.create_task(execute(providers={Route.NATIVE: provider}))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_document_deadline_includes_queued_regions(monkeypatch):
    import akc_router.document_execution as execution

    clock = [0.0]
    monkeypatch.setattr(execution, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    calls = []

    async def provider(binding):
        calls.append(binding.region_id)
        # Advancing the injected document clock makes the queue/deadline boundary
        # deterministic. A loaded Windows machine may exhaust a 10ms wall-clock
        # budget before the first provider starts, which is valid refusal, not
        # the queue behavior this particular regression is intended to test.
        clock[0] = 1.0
        return await native(binding)

    result = await execute(
        plan(("r1", "r2"), parallel=1),
        {"r1": work(), "r2": work("r2")},
        {Route.NATIVE: provider},
        deadline_seconds=0.01,
    )
    assert calls == ["r1"]
    assert len(result.regions) == 2
    assert result.regions["r2"].reasons == ("DOCUMENT_DEADLINE_REACHED",)


@pytest.mark.asyncio
@pytest.mark.parametrize("deadline", [0, -1, float("nan"), float("inf"), 181])
async def test_invalid_deadline_fails_before_work(deadline):
    with pytest.raises(ValueError, match="DEADLINE"):
        await execute(deadline_seconds=deadline)


@pytest.mark.asyncio
async def test_unqualified_parallel_capacity_is_refused_not_silently_raised():
    with pytest.raises(ValueError, match="CAPACITY_UNQUALIFIED"):
        await execute(plan(parallel=33))


@pytest.mark.asyncio
async def test_unresolved_plan_has_no_execution_authority():
    p = plan().model_copy(update={"unresolved_constraints": ("no-quality-receipt",)})
    with pytest.raises(ValueError, match="NOT_EXECUTABLE"):
        await execute(p)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [False, None, "true", 1])
async def test_standalone_region_authorization_must_explicitly_allow(value):
    item = work()
    calls = []

    async def provider(binding):
        calls.append(binding)
        return await native(binding)

    result = await execute_text_region(
        binding=item.binding,
        witness=item.witness,
        attempts=item.attempts,
        providers={Route.NATIVE: provider},
        permitted_routes=frozenset({Route.NATIVE}),
        cost_budget=1,
        deadline_seconds=1,
        authorization_valid=lambda: value,
    )
    assert calls == []
    assert result.reserved_cost == 0
    assert result.reasons == ("EXECUTION_AUTHORIZATION_REVOKED",)
