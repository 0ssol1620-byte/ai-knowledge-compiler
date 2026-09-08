"""§8 dependency DAG, §10 scheduler, §50 observability record."""

from __future__ import annotations

import pytest
from akc_router.dependency import UnitStructure, build_dependency_edges
from akc_router.execution_plan import DeadlineClass, DependencyKind, VerificationPolicy
from akc_router.models import Route
from akc_router.observability import FinalDisposition, RouterExecutionRecord
from akc_router.scheduler import (
    BackpressureError,
    CircuitOpenError,
    Scheduler,
    SchedulerError,
    SchedulerPolicy,
    Task,
    TaskState,
    simulate,
)
from pydantic import ValidationError

# --- §8 dependency DAG -------------------------------------------------------


def _known(unit_id: str, index: int, **overrides: object) -> UnitStructure:
    """A unit whose reader answered every question. Overrides say what it saw."""
    values: dict[str, object] = {
        "unit_id": unit_id,
        "page_index0": index,
        "table_runs_to_bottom": False,
        "table_resumes_at_top": False,
        "table_column_signature": None,
        "footnote_definitions": (),
        "footnote_references": (),
        "figure_ids": (),
        "caption_references": (),
        "image_callout_references": (),
        "formula_precedent_unit_ids": (),
    }
    values.update(overrides)
    return UnitStructure(**values)  # type: ignore[arg-type]


def test_a_continued_table_needs_both_sides_and_matching_columns() -> None:
    graph = build_dependency_edges(
        [
            _known("p1", 0, table_runs_to_bottom=True, table_column_signature="a|b|c"),
            _known("p2", 1, table_resumes_at_top=True, table_column_signature="a|b|c"),
        ]
    )
    assert graph.edges == (graph.edges[0],)
    assert graph.edges[0].kind is DependencyKind.CONTINUED_TABLE
    assert (graph.edges[0].from_unit_id, graph.edges[0].to_unit_id) == ("p1", "p2")


def test_different_columns_are_not_a_continued_table() -> None:
    graph = build_dependency_edges(
        [
            _known("p1", 0, table_runs_to_bottom=True, table_column_signature="a|b"),
            _known("p2", 1, table_resumes_at_top=True, table_column_signature="x|y|z"),
        ]
    )
    assert graph.edges == ()
    assert graph.unknown == ()


def test_an_unreadable_structure_records_unknown_and_builds_no_edge() -> None:
    graph = build_dependency_edges(
        [
            _known("p1", 0, table_runs_to_bottom=True, table_column_signature="a|b"),
            UnitStructure(unit_id="p2", page_index0=1),  # everything None
        ]
    )
    assert graph.edges == ()
    kinds = {kind for _, kind in graph.unknown}
    assert DependencyKind.CONTINUED_TABLE in kinds
    assert DependencyKind.FOOTNOTE in kinds
    assert any(signal.startswith("dependency_unknown:") for signal in graph.signals)


def test_columns_unknown_on_an_otherwise_matching_pair_is_unknown_not_an_edge() -> None:
    graph = build_dependency_edges(
        [
            _known("p1", 0, table_runs_to_bottom=True),
            _known("p2", 1, table_resumes_at_top=True),
        ]
    )
    assert graph.edges == ()
    assert ("p2", DependencyKind.CONTINUED_TABLE) in graph.unknown


def test_footnote_definition_lands_before_its_reference() -> None:
    graph = build_dependency_edges(
        [
            _known("p1", 0, footnote_references=("12",)),
            _known("p2", 1, footnote_definitions=("12",)),
        ]
    )
    edge = graph.edges[0]
    assert edge.kind is DependencyKind.FOOTNOTE
    assert (edge.from_unit_id, edge.to_unit_id) == ("p2", "p1")


def test_figure_caption_and_image_callout_link_to_the_owning_unit() -> None:
    graph = build_dependency_edges(
        [
            _known("p1", 0, figure_ids=("fig-1",)),
            _known("p2", 1, caption_references=("fig-1",), image_callout_references=("fig-1",)),
        ]
    )
    kinds = {edge.kind for edge in graph.edges}
    assert kinds == {DependencyKind.FIGURE_CAPTION, DependencyKind.IMAGE_CALLOUT}
    assert all(edge.from_unit_id == "p1" for edge in graph.edges)


def test_office_and_mail_natives_build_their_own_edges() -> None:
    graph = build_dependency_edges(
        [
            _known("slide-1", 0),
            _known("notes-1", 1, slide_notes_for_unit_id="slide-1"),
            _known("sheet-a", 2),
            _known("sheet-b", 3, formula_precedent_unit_ids=("sheet-a",)),
            _known("mail-1", 4),
            _known("att-1", 5, attachment_of_unit_id="mail-1"),
            _known("ctx-1", 6),
            _known("fact-1", 7, xbrl_context_unit_id="ctx-1"),
        ]
    )
    kinds = {edge.kind for edge in graph.edges}
    assert kinds == {
        DependencyKind.SLIDE_NOTES,
        DependencyKind.SHEET_FORMULA,
        DependencyKind.EMAIL_ATTACHMENT,
        DependencyKind.XBRL_CONTEXT,
    }


def test_a_dangling_precedent_is_unknown_not_an_edge() -> None:
    graph = build_dependency_edges(
        [_known("sheet-b", 0, formula_precedent_unit_ids=("sheet-missing",))]
    )
    assert graph.edges == ()
    assert ("sheet-b", DependencyKind.SHEET_FORMULA) in graph.unknown


def test_dependency_building_is_deterministic() -> None:
    structures = [
        _known("p1", 0, figure_ids=("f1",), footnote_definitions=("1",)),
        _known("p2", 1, caption_references=("f1",), footnote_references=("1",)),
    ]
    assert build_dependency_edges(structures) == build_dependency_edges(list(reversed(structures)))


# --- §10 scheduler -----------------------------------------------------------


def _task(task_id: str, tenant: str, **overrides: object) -> Task:
    values: dict[str, object] = {
        "task_id": task_id,
        "tenant_id": tenant,
        "route": Route.PADDLE_FAST,
    }
    values.update(overrides)
    return Task(**values)  # type: ignore[arg-type]


def test_a_five_thousand_page_document_does_not_starve_another_tenant() -> None:
    """The §10 property, asserted rather than asserted-about."""
    big = [_task(f"big-{index:05d}", "big") for index in range(5_000)]
    small = [_task(f"small-{index}", "small") for index in range(10)]
    policy = SchedulerPolicy(route_capacity={Route.PADDLE_FAST: 8}, per_tenant_concurrency=2)
    result = simulate([*big, *small], policy)
    small_done = result.last_completion("small")
    assert small_done is not None
    # The small tenant finishes in its own handful of ticks, not behind 5,000
    # pages of someone else's document.
    assert small_done <= 10
    assert result.last_completion("big") is not None
    assert result.last_completion("big") > small_done


def test_per_tenant_concurrency_is_enforced() -> None:
    scheduler = Scheduler(SchedulerPolicy(route_capacity={Route.PADDLE_FAST: 8}))
    scheduler.submit_wave(_task(f"t-{index}", "one") for index in range(6))
    started = scheduler.dispatch()
    assert len(started) == 2
    assert scheduler.running_count() == 2


def test_a_wave_is_a_barrier() -> None:
    scheduler = Scheduler(SchedulerPolicy(per_tenant_concurrency=4))
    scheduler.submit(_task("w1", "one", wave_index=0))
    scheduler.submit(_task("w2", "one", wave_index=1))
    assert {task.task_id for task in scheduler.dispatch()} == {"w1"}


def test_queue_aging_lifts_a_waiting_batch_task() -> None:
    clock = {"now": 0.0}
    policy = SchedulerPolicy(
        route_capacity={Route.PADDLE_FAST: 1},
        per_tenant_concurrency=1,
        aging_priority_per_second=10.0,
    )
    scheduler = Scheduler(policy, clock=lambda: clock["now"])
    scheduler.submit(_task("old-batch", "one", deadline_class=DeadlineClass.BATCH, priority=100))
    clock["now"] = 100.0
    scheduler.submit(
        _task("new-interactive", "one", deadline_class=DeadlineClass.INTERACTIVE, priority=800)
    )
    # 100 + 1000 aged beats 800 + 250 fresh.
    assert {task.task_id for task in scheduler.dispatch()} == {"old-batch"}


def test_interactive_beats_batch_at_equal_age() -> None:
    policy = SchedulerPolicy(route_capacity={Route.PADDLE_FAST: 1}, per_tenant_concurrency=1)
    scheduler = Scheduler(policy)
    scheduler.submit(_task("batch", "one", deadline_class=DeadlineClass.BATCH, priority=500))
    scheduler.submit(
        _task("interactive", "one", deadline_class=DeadlineClass.INTERACTIVE, priority=500)
    )
    assert {task.task_id for task in scheduler.dispatch()} == {"interactive"}


def test_backpressure_refuses_instead_of_growing_the_queue() -> None:
    scheduler = Scheduler(SchedulerPolicy(max_queue_depth=2))
    scheduler.submit(_task("a", "one"))
    scheduler.submit(_task("b", "one"))
    with pytest.raises(BackpressureError):
        scheduler.submit(_task("c", "one"))


def test_speculative_work_is_capped() -> None:
    policy = SchedulerPolicy(
        route_capacity={Route.PADDLE_FAST: 8},
        per_tenant_concurrency=8,
        max_speculative_in_flight=1,
    )
    scheduler = Scheduler(policy)
    scheduler.submit_wave(_task(f"s-{index}", "one", speculative=True) for index in range(4))
    assert len(scheduler.dispatch()) == 1


def test_the_circuit_breaker_opens_then_recovers() -> None:
    clock = {"now": 0.0}
    policy = SchedulerPolicy(
        route_capacity={Route.PADDLE_FAST: 1},
        per_tenant_concurrency=1,
        breaker_failure_threshold=2,
        breaker_cooldown_seconds=30.0,
        max_attempts=1,
    )
    scheduler = Scheduler(policy, clock=lambda: clock["now"])
    for index in range(2):
        scheduler.submit(_task(f"f-{index}", "one"))
        started = scheduler.dispatch()
        scheduler.complete(started[0].task_id, success=False)
    assert scheduler.breaker_open(Route.PADDLE_FAST)
    with pytest.raises(CircuitOpenError):
        scheduler.submit(_task("blocked", "one"))
    clock["now"] = 31.0
    assert not scheduler.breaker_open(Route.PADDLE_FAST)
    scheduler.submit(_task("allowed", "one"))


def test_retry_is_bounded() -> None:
    policy = SchedulerPolicy(max_attempts=2, breaker_failure_threshold=99)
    scheduler = Scheduler(policy)
    scheduler.submit(_task("r", "one"))
    first = scheduler.dispatch()[0]
    retry = scheduler.complete(first.task_id, success=False)
    assert retry is not None
    assert retry.attempt == 2
    scheduler.submit(retry)
    second = scheduler.dispatch()[0]
    assert scheduler.complete(second.task_id, success=False) is None


def test_an_attempt_beyond_the_bound_is_refused() -> None:
    scheduler = Scheduler(SchedulerPolicy(max_attempts=2))
    with pytest.raises(SchedulerError):
        scheduler.submit(_task("r", "one", attempt=3))


def test_cancellation_removes_queued_work_for_one_tenant() -> None:
    scheduler = Scheduler(SchedulerPolicy(per_tenant_concurrency=0))
    scheduler.submit_wave([_task("a", "one"), _task("b", "one"), _task("c", "two")])
    assert scheduler.cancel(tenant_id="one") == 2
    assert scheduler.state("a") is TaskState.CANCELLED
    assert scheduler.queue_depth() == 1
    with pytest.raises(SchedulerError):
        scheduler.cancel(task_id="c", tenant_id="two")


def test_completing_a_task_that_is_not_running_is_an_error() -> None:
    scheduler = Scheduler()
    with pytest.raises(SchedulerError):
        scheduler.complete("nothing", success=True)


def test_simulation_is_deterministic() -> None:
    tasks = [_task(f"t-{index}", f"tenant-{index % 3}") for index in range(30)]
    assert simulate(tasks).dispatched == simulate(tasks).dispatched


# --- §50 observability record ------------------------------------------------


def _record(**overrides: object) -> RouterExecutionRecord:
    values: dict[str, object] = {
        "unit_id": "sv-1#page-3",
        "source_version_id": "sv-1",
        "planner_revision": "planner-v2.0.0-shadow",
        "feature_revision": "sha256:" + "0" * 64,
        "portfolio_revision": "portfolio_0123456789abcdef",
        "route": Route.PADDLE_FAST,
        "candidate_routes": (Route.PADDLE_FAST, Route.PADDLE_VL),
        "final_disposition": FinalDisposition.ACCEPTED,
    }
    values.update(overrides)
    return RouterExecutionRecord.model_validate(values)


def test_the_record_carries_every_section_fifty_field() -> None:
    record = _record(
        speculative_routes=(Route.PADDLE_VL,),
        queue_time_ms=120.0,
        latency_ms=3400.0,
        runtime_digest="sha256:" + "a" * 64,
        retry_count=1,
        verifier=VerificationPolicy.PEER_AGREEMENT,
        verifier_passed=True,
        escalations=("primary_route_quality_failed",),
        region_recovery_count=2,
        evidence_locator="s3://evidence/sv-1/page-3",
        cost_credits=2.6,
    )
    dumped = record.model_dump(mode="json", by_alias=True)
    for wire_name in (
        "sourceVersionId",
        "plannerRevision",
        "featureRevision",
        "portfolioRevision",
        "route",
        "candidateRoutes",
        "speculativeRoutes",
        "queueTimeMs",
        "runtimeDigest",
        "retryCount",
        "verifier",
        "escalations",
        "regionRecoveryCount",
        "finalDisposition",
        "evidenceLocator",
        "costCredits",
        "latencyMs",
    ):
        assert wire_name in dumped


def test_no_raw_source_text_can_enter_the_record() -> None:
    """Every free-text-shaped field rejects prose, not just long prose."""
    sentence = "Revenue for the quarter was $4,201,993 across three segments."
    for field_name in ("unit_id", "source_version_id", "evidence_locator"):
        with pytest.raises(ValidationError):
            _record(**{field_name: sentence})
    with pytest.raises(ValidationError):
        _record(escalations=(sentence,))
    with pytest.raises(ValidationError):
        _record(reason_codes=(sentence,))
    with pytest.raises(ValidationError):
        _record(unit_id="a" * 500)
    with pytest.raises(ValidationError):
        _record(reason_codes=tuple(f"code-{index}" for index in range(65)))


def test_a_mutable_tag_is_not_a_runtime_digest() -> None:
    with pytest.raises(ValidationError):
        _record(runtime_digest="vllm/vllm-openai:v0.19.0")


def test_the_record_is_uncalibrated_by_default() -> None:
    assert _record().calibrated is False
