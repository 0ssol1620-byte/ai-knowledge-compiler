"""In-process execution scheduler (program §10, blueprint §22/§67).

No Kafka, no Kubernetes, no broker. This is a deterministic in-process
admission and dispatch policy: given the tasks waiting, the clock and the
capacity, decide which may start now. Anything durable lives in PostgreSQL and
object storage, and adding infrastructure needs a measured bottleneck and an
ADR (`CLAUDE.md`).

The property this exists to guarantee is the one the program states outright:
**a 5,000-page document must not block another tenant.** Dispatch is
tenant-round-robin under a per-tenant concurrency cap, so a huge document
occupies its share and no more, however early it arrived.

Determinism is a feature, not an accident: the clock is injected, ordering is
total, and `simulate` runs a whole workload with no wall-clock sleep so the
fairness property can be asserted in a test rather than argued about.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from .execution_plan import DeadlineClass
from .models import Route


class SchedulerError(RuntimeError):
    """Base class. Every rejection is explicit; nothing is dropped silently."""


class BackpressureError(SchedulerError):
    """The queue is full. The caller retries later; it does not grow the queue."""


class CircuitOpenError(SchedulerError):
    """A route's breaker is open. Admitting more work would just fail more."""


class TaskState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    tenant_id: str
    route: Route
    wave_index: int = 0
    deadline_class: DeadlineClass = DeadlineClass.STANDARD
    speculative: bool = False
    priority: int = 500
    attempt: int = 1


@dataclass(slots=True)
class _Entry:
    task: Task
    enqueued_at: float
    state: TaskState = TaskState.QUEUED
    started_at: float | None = None


@dataclass(frozen=True, slots=True)
class SchedulerPolicy:
    """Uncalibrated. Every number here is an operating choice, not a finding."""

    route_capacity: dict[Route, int] = field(default_factory=dict)
    default_route_capacity: int = 4
    per_tenant_concurrency: int = 2
    max_queue_depth: int = 10_000
    max_speculative_in_flight: int = 2
    breaker_failure_threshold: int = 5
    breaker_cooldown_seconds: float = 30.0
    max_attempts: int = 3
    #: Priority added per second a task has waited. Ageing is what stops a batch
    #: tenant starving behind a stream of interactive work.
    aging_priority_per_second: float = 1.0
    interactive_priority_bonus: int = 250

    def capacity_for(self, route: Route) -> int:
        return self.route_capacity.get(route, self.default_route_capacity)


class Scheduler:
    """Model-specific queues, tenant fairness, backpressure, breaker, retry."""

    def __init__(
        self,
        policy: SchedulerPolicy | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._policy = policy or SchedulerPolicy()
        self._now = clock or (lambda: 0.0)
        self._queues: dict[Route, list[_Entry]] = {}
        self._running: dict[str, _Entry] = {}
        self._states: dict[str, TaskState] = {}
        self._consecutive_failures: dict[Route, int] = {}
        self._breaker_opened_at: dict[Route, float] = {}

    # --- admission ----------------------------------------------------------

    def submit(self, task: Task) -> None:
        """Admit a task, or refuse it out loud."""
        if self.breaker_open(task.route):
            raise CircuitOpenError(f"circuit open for route {task.route.value}")
        if self.queue_depth() >= self._policy.max_queue_depth:
            raise BackpressureError("scheduler queue is full")
        if task.attempt > self._policy.max_attempts:
            raise SchedulerError(
                f"attempt {task.attempt} exceeds max_attempts {self._policy.max_attempts}"
            )
        if task.task_id in self._running or (
            task.task_id in self._states
            and self._states[task.task_id]
            in {
                TaskState.QUEUED,
                TaskState.RUNNING,
            }
        ):
            raise SchedulerError(f"task {task.task_id} is already in flight")
        self._queues.setdefault(task.route, []).append(_Entry(task=task, enqueued_at=self._now()))
        self._states[task.task_id] = TaskState.QUEUED

    def submit_wave(self, tasks: Iterable[Task]) -> None:
        for task in tasks:
            self.submit(task)

    # --- dispatch -----------------------------------------------------------

    def dispatch(self) -> tuple[Task, ...]:
        """Return the tasks that may start now, and mark them running.

        Only the lowest queued wave index of each tenant is eligible: a wave is
        a barrier, so a continued table never starts before the page it
        continues from.
        """
        started: list[Task] = []
        now = self._now()
        for route in sorted(self._queues, key=lambda item: item.value):
            queue = self._queues[route]
            if not queue:
                continue
            free = self._policy.capacity_for(route) - self._running_on(route)
            if free <= 0:
                continue
            if self.breaker_open(route):
                continue
            for entry in self._eligible(queue, now):
                if free <= 0:
                    break
                if not self._tenant_has_room(entry.task.tenant_id):
                    continue
                if entry.task.speculative and not self._speculative_has_room():
                    continue
                entry.state = TaskState.RUNNING
                entry.started_at = now
                self._running[entry.task.task_id] = entry
                self._states[entry.task.task_id] = TaskState.RUNNING
                queue.remove(entry)
                started.append(entry.task)
                free -= 1
        return tuple(started)

    def _eligible(self, queue: Sequence[_Entry], now: float) -> list[_Entry]:
        """Round-robin over tenants, then by aged priority inside each tenant.

        The outer key is the tenant's *in-flight count*, which is the whole
        fairness mechanism: a tenant already running work sorts behind one that
        is not, whatever its priority or arrival order.
        """
        barrier: dict[str, int] = {}
        # A wave belongs to the tenant, not to a provider queue. Earlier work
        # remains a barrier after dispatch until its worker actually completes.
        # Cancelled running entries still occupy capacity and hold this barrier;
        # their computation has not stopped merely because delivery is cancelled.
        for entries in (*self._queues.values(), tuple(self._running.values())):
            for entry in entries:
                tenant = entry.task.tenant_id
                barrier[tenant] = min(
                    barrier.get(tenant, entry.task.wave_index), entry.task.wave_index
                )
        ready = [entry for entry in queue if entry.task.wave_index == barrier[entry.task.tenant_id]]
        return sorted(
            ready,
            key=lambda entry: (
                self._tenant_running(entry.task.tenant_id),
                -self.effective_priority(entry, now),
                entry.enqueued_at,
                entry.task.task_id,
            ),
        )

    def effective_priority(self, entry: _Entry, now: float) -> float:
        waited = max(0.0, now - entry.enqueued_at)
        bonus = (
            self._policy.interactive_priority_bonus
            if entry.task.deadline_class is DeadlineClass.INTERACTIVE
            else 0
        )
        return entry.task.priority + bonus + waited * self._policy.aging_priority_per_second

    # --- completion ---------------------------------------------------------

    def complete(self, task_id: str, *, success: bool) -> Task | None:
        """Finish a running task. Returns a retry task when one is warranted."""
        entry = self._running.pop(task_id, None)
        if entry is None:
            raise SchedulerError(f"task {task_id} is not running")
        if entry.state is TaskState.CANCELLED:
            # No successful publication and no retry after cancellation. Do not
            # count an intentional cancellation as a provider-health failure.
            self._states[task_id] = TaskState.CANCELLED
            return None
        route = entry.task.route
        if success:
            entry.state = TaskState.SUCCEEDED
            self._states[task_id] = TaskState.SUCCEEDED
            self._consecutive_failures[route] = 0
            return None
        entry.state = TaskState.FAILED
        self._states[task_id] = TaskState.FAILED
        failures = self._consecutive_failures.get(route, 0) + 1
        self._consecutive_failures[route] = failures
        if failures >= self._policy.breaker_failure_threshold:
            self._breaker_opened_at[route] = self._now()
        if entry.task.attempt >= self._policy.max_attempts:
            return None
        # Bounded retry: a new attempt, never an unbounded resubmission loop.
        retry = Task(
            task_id=f"{entry.task.task_id}#a{entry.task.attempt + 1}",
            tenant_id=entry.task.tenant_id,
            route=route,
            wave_index=entry.task.wave_index,
            deadline_class=entry.task.deadline_class,
            speculative=entry.task.speculative,
            priority=entry.task.priority,
            attempt=entry.task.attempt + 1,
        )
        return retry

    def cancel(self, *, task_id: str | None = None, tenant_id: str | None = None) -> int:
        """Cancel a queued task or a tenant's queued work. Running work is not
        killed here -- the worker owns that -- but it is marked so its result is
        discarded on completion."""
        if (task_id is None) == (tenant_id is None):
            raise SchedulerError("cancel exactly one of task_id or tenant_id")
        cancelled = 0
        for entry in self._running.values():
            if task_id is not None and entry.task.task_id != task_id:
                continue
            if tenant_id is not None and entry.task.tenant_id != tenant_id:
                continue
            if entry.state is TaskState.CANCELLED:
                continue
            entry.state = TaskState.CANCELLED
            self._states[entry.task.task_id] = TaskState.CANCELLED
            cancelled += 1
        for queue in self._queues.values():
            for entry in list(queue):
                if task_id is not None and entry.task.task_id != task_id:
                    continue
                if tenant_id is not None and entry.task.tenant_id != tenant_id:
                    continue
                queue.remove(entry)
                entry.state = TaskState.CANCELLED
                self._states[entry.task.task_id] = TaskState.CANCELLED
                cancelled += 1
        return cancelled

    # --- introspection ------------------------------------------------------

    def breaker_open(self, route: Route) -> bool:
        opened = self._breaker_opened_at.get(route)
        if opened is None:
            return False
        if self._now() - opened >= self._policy.breaker_cooldown_seconds:
            del self._breaker_opened_at[route]
            self._consecutive_failures[route] = 0
            return False
        return True

    def state(self, task_id: str) -> TaskState | None:
        return self._states.get(task_id)

    def queue_depth(self, route: Route | None = None) -> int:
        if route is not None:
            return len(self._queues.get(route, ()))
        return sum(len(queue) for queue in self._queues.values())

    def running_count(self) -> int:
        return len(self._running)

    def _running_on(self, route: Route) -> int:
        return sum(1 for entry in self._running.values() if entry.task.route == route)

    def _tenant_running(self, tenant_id: str) -> int:
        return sum(1 for entry in self._running.values() if entry.task.tenant_id == tenant_id)

    def _tenant_has_room(self, tenant_id: str) -> bool:
        return self._tenant_running(tenant_id) < self._policy.per_tenant_concurrency

    def _speculative_has_room(self) -> bool:
        in_flight = sum(1 for entry in self._running.values() if entry.task.speculative)
        return in_flight < self._policy.max_speculative_in_flight


@dataclass(frozen=True, slots=True)
class SimulationResult:
    ticks: int
    completed_at: dict[str, int]
    dispatched: tuple[tuple[int, str], ...]

    def first_completion(self, tenant_id: str) -> int | None:
        ticks = [
            tick for task_id, tick in self.completed_at.items() if task_id.startswith(tenant_id)
        ]
        return min(ticks) if ticks else None

    def last_completion(self, tenant_id: str) -> int | None:
        ticks = [
            tick for task_id, tick in self.completed_at.items() if task_id.startswith(tenant_id)
        ]
        return max(ticks) if ticks else None


def simulate(
    tasks: Sequence[Task],
    policy: SchedulerPolicy | None = None,
    *,
    max_ticks: int = 100_000,
) -> SimulationResult:
    """Run a workload to completion on a virtual clock. One tick = one second.

    Every dispatched task completes successfully on the following tick. That is
    deliberately unrealistic -- the point is to observe the *ordering* the
    policy produces, with no timing noise to argue about.
    """
    tick = 0
    clock = {"now": 0.0}
    scheduler = Scheduler(policy, clock=lambda: clock["now"])
    scheduler.submit_wave(tasks)
    in_flight: list[str] = []
    completed_at: dict[str, int] = {}
    dispatched: list[tuple[int, str]] = []
    while tick < max_ticks:
        for task_id in in_flight:
            scheduler.complete(task_id, success=True)
            completed_at[task_id] = tick
        in_flight = [task.task_id for task in scheduler.dispatch()]
        dispatched.extend((tick, task_id) for task_id in in_flight)
        if not in_flight and scheduler.queue_depth() == 0:
            break
        tick += 1
        clock["now"] = float(tick)
    return SimulationResult(ticks=tick, completed_at=completed_at, dispatched=tuple(dispatched))


__all__ = [
    "BackpressureError",
    "CircuitOpenError",
    "Scheduler",
    "SchedulerError",
    "SchedulerPolicy",
    "SimulationResult",
    "Task",
    "TaskState",
    "simulate",
]
