"""Observed scheduler invariants; deterministic fixtures, not quality claims."""

from __future__ import annotations

import pytest
from akc_router.models import Route
from akc_router.scheduler import Scheduler, SchedulerError, SchedulerPolicy, Task, TaskState


def scheduler() -> Scheduler:
    return Scheduler(SchedulerPolicy(default_route_capacity=4, per_tenant_concurrency=4))


def test_later_wave_waits_for_other_route_to_finish() -> None:
    s = scheduler()
    s.submit_wave(
        [
            Task("first", "tenant-a", Route.PADDLE_VL, wave_index=0),
            Task("dependent", "tenant-a", Route.NATIVE, wave_index=1),
        ]
    )
    assert [t.task_id for t in s.dispatch()] == ["first"]
    assert s.dispatch() == ()
    s.complete("first", success=True)
    assert [t.task_id for t in s.dispatch()] == ["dependent"]


def test_running_same_route_wave_remains_a_barrier() -> None:
    s = scheduler()
    s.submit(Task("first", "tenant-a", Route.NATIVE, wave_index=0))
    assert len(s.dispatch()) == 1
    s.submit(Task("next", "tenant-a", Route.NATIVE, wave_index=1))
    assert s.dispatch() == ()
    s.complete("first", success=True)
    assert [t.task_id for t in s.dispatch()] == ["next"]


def test_barrier_does_not_serialize_different_tenants() -> None:
    s = scheduler()
    s.submit_wave(
        [
            Task("a0", "tenant-a", Route.NATIVE, wave_index=0),
            Task("a1", "tenant-a", Route.PADDLE_VL, wave_index=1),
            Task("b1", "tenant-b", Route.PADDLE_VL, wave_index=1),
        ]
    )
    assert {t.task_id for t in s.dispatch()} == {"a0", "b1"}


def test_same_wave_independent_routes_run_together() -> None:
    s = scheduler()
    s.submit_wave([Task("cpu", "a", Route.NATIVE), Task("visual", "a", Route.PADDLE_VL)])
    assert {t.task_id for t in s.dispatch()} == {"cpu", "visual"}


@pytest.mark.parametrize("success", [True, False])
def test_cancelled_running_work_keeps_capacity_until_worker_exits(success: bool) -> None:
    s = Scheduler(SchedulerPolicy(default_route_capacity=1, per_tenant_concurrency=1))
    s.submit(Task("running", "a", Route.NATIVE))
    assert len(s.dispatch()) == 1
    assert s.cancel(task_id="running") == 1
    assert s.state("running") is TaskState.CANCELLED
    assert s.running_count() == 1
    assert s.cancel(task_id="running") == 0
    with pytest.raises(SchedulerError, match="already in flight"):
        s.submit(Task("running", "a", Route.NATIVE))
    s.submit(Task("waiting", "b", Route.NATIVE))
    assert s.dispatch() == ()
    assert s.complete("running", success=success) is None
    assert s.state("running") is TaskState.CANCELLED
    assert [t.task_id for t in s.dispatch()] == ["waiting"]


def test_tenant_cancel_marks_running_and_removes_queued() -> None:
    s = Scheduler(SchedulerPolicy(per_tenant_concurrency=1))
    s.submit_wave([Task("active", "a", Route.NATIVE), Task("queued", "a", Route.NATIVE)])
    assert len(s.dispatch()) == 1
    assert s.cancel(tenant_id="a") == 2
    assert s.queue_depth() == 0
    assert s.running_count() == 1
    assert s.complete("active", success=True) is None
    assert s.state("active") is TaskState.CANCELLED
    assert s.state("queued") is TaskState.CANCELLED
