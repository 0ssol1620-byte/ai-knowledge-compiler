"""Watchdogs — masterplan sections 15.4, 15.5, 15.10, 15.11, 15.12, 15.13, 36.

Every watchdog is a pure function of observed state and a clock. They return
findings; applying a finding (draining a worker, pausing the queue) is
``run.py``'s job. That split is what makes "budget hard cap drains without
killing an in-flight page" a thing a test can assert.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from arena.constants import (
    BUDGET_HARD_CAP_USD,
    BUDGET_SOFT_CAP_USD,
    HEARTBEAT_INTERVAL_SECONDS,
)
from arena.controller.paths import CampaignPaths
from arena.controller.runtime_spec import RuntimeSpecError, load_runtime_spec

__all__ = [
    "BUDGET_STATES",
    "CANARY_MAX_POD_LIFETIME_SECONDS",
    "FULL_RUN_MAX_POD_LIFETIME_SECONDS",
    "BudgetAssessment",
    "BudgetWatchdog",
    "CircuitBreaker",
    "CircuitBreakerTrip",
    "Finding",
    "IdleDecision",
    "StragglerFinding",
    "WorkerObservation",
    "heartbeat_findings",
    "idle_grace_seconds",
    "idle_killer",
    "lifetime_expiry",
    "max_pod_lifetime_seconds",
    "model_stall_thresholds",
    "stall_threshold_seconds",
    "straggler_check",
]

MAX_POD_LIFETIME_SECONDS: Final = 6 * 3600  # masterplan section 15.12 default
# ARENA_CONTRACT section 11 D10: a canary pod lives at most two hours.
CANARY_MAX_POD_LIFETIME_SECONDS: Final = 2 * 3600
FULL_RUN_MAX_POD_LIFETIME_SECONDS: Final = MAX_POD_LIFETIME_SECONDS
MISSED_HEARTBEATS_BEFORE_STALL: Final = 3
STRAGGLER_FACTOR: Final = 1.5  # masterplan section 36
STALL_MULTIPLIER: Final = 3.0  # masterplan section 15.5
SMALL_MODEL_IDLE_GRACE_SECONDS: Final = 5 * 60
LARGE_MODEL_IDLE_GRACE_SECONDS: Final = 10 * 60
BUDGET_STATES: Final = ("NORMAL", "SOFT_CAP", "HARD_CAP")


@dataclass(frozen=True, slots=True)
class Finding:
    """Something a watchdog observed and what it wants done about it."""

    kind: str
    entity_kind: str
    entity_id: str
    action: str
    reason: str
    detail: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkerObservation:
    worker_id: str
    model_key: str
    state: str
    last_heartbeat_at: str | None
    current_job_id: str | None = None
    job_elapsed_seconds: float | None = None
    gpu_util_percent: float | None = None
    pod_provisioned_at: str | None = None
    idle_seconds: float = 0.0


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def stall_threshold_seconds(
    canary_p95_seconds: float | None,
    model_minimum_seconds: float,
) -> float:
    """``max(3 x canary_p95, model_minimum)`` (masterplan section 15.5).

    With no canary measurement the threshold is the model minimum alone; the
    caller is told which by the returned value equalling the minimum. A single
    fixed timeout for every model is exactly what section 15.5 forbids.
    """

    if model_minimum_seconds <= 0:
        raise ValueError("a model-specific minimum timeout is required")
    if canary_p95_seconds is None or canary_p95_seconds <= 0:
        return model_minimum_seconds
    return max(STALL_MULTIPLIER * canary_p95_seconds, model_minimum_seconds)


def model_stall_thresholds(
    paths: CampaignPaths,
    model_keys: Sequence[str],
    *,
    canary_p95_seconds: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Per-model stall thresholds, floored at ``per_page_timeout_seconds``.

    ARENA_CONTRACT section 11 D13. The floor comes from the runtime the C lane
    wrote, so a model whose pages legitimately take ten minutes is never
    declared stalled at three. A model whose ``runtime.json`` cannot be read is
    left out of the mapping rather than given a default -- the caller then has
    no threshold for it and must say so, instead of silently killing workers on
    a number nobody chose.
    """

    measured = dict(canary_p95_seconds or {})
    thresholds: dict[str, float] = {}
    for model_key in model_keys:
        try:
            runtime = load_runtime_spec(paths.runtime_json(model_key), model_key)
        except RuntimeSpecError:
            continue
        thresholds[model_key] = stall_threshold_seconds(
            measured.get(model_key), float(runtime.per_page_timeout_seconds)
        )
    return thresholds


def max_pod_lifetime_seconds(job_kind: str) -> int:
    """D10: 2 h for a canary pod, 6 h for a full-run pod."""

    if job_kind == "canary":
        return CANARY_MAX_POD_LIFETIME_SECONDS
    return FULL_RUN_MAX_POD_LIFETIME_SECONDS


def heartbeat_findings(
    workers: Sequence[WorkerObservation],
    *,
    now: datetime,
    interval_seconds: int = HEARTBEAT_INTERVAL_SECONDS,
    stall_thresholds: Mapping[str, float] | None = None,
) -> tuple[Finding, ...]:
    """Missing heartbeats and per-model job stalls (sections 15.4, 15.5)."""

    thresholds = dict(stall_thresholds or {})
    silence_limit = interval_seconds * MISSED_HEARTBEATS_BEFORE_STALL
    findings: list[Finding] = []
    for worker in workers:
        if worker.state in {"TERMINATED", "QUARANTINED"}:
            continue
        last = _parse_iso(worker.last_heartbeat_at)
        if last is None:
            findings.append(
                Finding(
                    kind="heartbeat_missing",
                    entity_kind="worker",
                    entity_id=worker.worker_id,
                    action="mark_stalled",
                    reason="no heartbeat has ever been recorded for this worker",
                    detail={"state": worker.state},
                )
            )
            continue
        silence = (now - last).total_seconds()
        if silence > silence_limit:
            findings.append(
                Finding(
                    kind="heartbeat_stall",
                    entity_kind="worker",
                    entity_id=worker.worker_id,
                    action="mark_stalled",
                    reason=(
                        f"{silence:.0f}s without a heartbeat exceeds "
                        f"{MISSED_HEARTBEATS_BEFORE_STALL} intervals ({silence_limit}s)"
                    ),
                    detail={"silence_seconds": silence},
                )
            )
        threshold = thresholds.get(worker.model_key)
        elapsed = worker.job_elapsed_seconds
        if threshold is not None and elapsed is not None and elapsed > threshold:
            findings.append(
                Finding(
                    kind="job_stall",
                    entity_kind="job",
                    entity_id=worker.current_job_id or worker.worker_id,
                    action="fail_job_inference_stall",
                    reason=(
                        f"job ran {elapsed:.0f}s past the {threshold:.0f}s dynamic stall threshold"
                    ),
                    detail={"worker_id": worker.worker_id, "threshold_seconds": threshold},
                )
            )
    return tuple(findings)


@dataclass(frozen=True, slots=True)
class StragglerFinding:
    shard_id: str
    elapsed_seconds: float
    threshold_seconds: float
    progressing: bool
    hedge_allowed: bool
    reason: str


def straggler_check(
    *,
    shard_id: str,
    elapsed_seconds: float,
    p95_expected_seconds: float,
    progressing: bool,
    source_corrupt: bool,
    healthy_spare_worker: bool,
    hedging_enabled: bool = False,
) -> StragglerFinding | None:
    """Masterplan section 36. Hedging is off unless every condition holds."""

    if p95_expected_seconds <= 0:
        raise ValueError("p95 expectation must be positive to diagnose a straggler")
    threshold = p95_expected_seconds * STRAGGLER_FACTOR
    if elapsed_seconds <= threshold:
        return None
    hedge_allowed = (
        hedging_enabled and not progressing and not source_corrupt and healthy_spare_worker
    )
    if hedge_allowed:
        reason = "no progress, source intact, spare worker free: one selective hedge permitted"
    elif not hedging_enabled:
        reason = "diagnose only; hedging is off by default (masterplan section 36)"
    else:
        reason = "hedging enabled but the section 36 preconditions are not all met"
    return StragglerFinding(
        shard_id=shard_id,
        elapsed_seconds=elapsed_seconds,
        threshold_seconds=threshold,
        progressing=progressing,
        hedge_allowed=hedge_allowed,
        reason=reason,
    )


@dataclass(frozen=True, slots=True)
class CircuitBreakerTrip:
    model_key: str
    rule: str
    reason: str
    detail: Mapping[str, object] = field(default_factory=dict)


class CircuitBreaker:
    """Masterplan section 15.10, rule for rule.

    On a trip the runtime goes DRAIN -> diagnostics -> terminate ->
    RUNTIME_QUARANTINED. It never resets itself: requalification is a canary,
    not a timer.
    """

    IDENTICAL_SIGNATURE_LIMIT: Final = 3
    FIRST_WINDOW: Final = 20
    FIRST_WINDOW_FAILURE_RATE: Final = 0.10
    MOVING_WINDOW: Final = 100
    MOVING_WINDOW_FAILURE_RATE: Final = 0.02

    def __init__(self, model_key: str) -> None:
        self.model_key = model_key
        self._outcomes: list[bool] = []
        self._signatures: list[str] = []
        self._trip: CircuitBreakerTrip | None = None

    @property
    def tripped(self) -> CircuitBreakerTrip | None:
        return self._trip

    def record(
        self, *, failed: bool, error_signature: str | None = None
    ) -> CircuitBreakerTrip | None:
        self._outcomes.append(failed)
        if failed and error_signature:
            self._signatures.append(error_signature)
        elif not failed:
            self._signatures.clear()
        return self._evaluate()

    def observe_heartbeat_stall(self, worker_id: str) -> CircuitBreakerTrip | None:
        return self._set_trip(
            "repeated_heartbeat_stall",
            f"worker {worker_id} stalled its heartbeat",
            {"worker_id": worker_id},
        )

    def observe_malformed_burst(self, count: int, window: int) -> CircuitBreakerTrip | None:
        return self._set_trip(
            "malformed_output_burst",
            f"{count} malformed outputs inside a {window}-job window",
            {"count": count, "window": window},
        )

    def observe_version_mismatch(self, expected: str, actual: str) -> CircuitBreakerTrip | None:
        return self._set_trip(
            "version_mismatch",
            "the worker reported a model or runtime version the registry does not pin",
            {"expected": expected, "actual": actual},
        )

    def observe_idle_gpu_while_busy(
        self, worker_id: str, gpu_util_percent: float, seconds: float
    ) -> CircuitBreakerTrip | None:
        return self._set_trip(
            "gpu_idle_while_busy",
            (
                f"worker {worker_id} held BUSY for {seconds:.0f}s at "
                f"{gpu_util_percent:.1f}% GPU utilization"
            ),
            {"worker_id": worker_id, "gpu_util_percent": gpu_util_percent},
        )

    def _evaluate(self) -> CircuitBreakerTrip | None:
        if len(self._signatures) >= self.IDENTICAL_SIGNATURE_LIMIT:
            tail = self._signatures[-self.IDENTICAL_SIGNATURE_LIMIT :]
            if len(set(tail)) == 1:
                return self._set_trip(
                    "identical_signature_streak",
                    f"{self.IDENTICAL_SIGNATURE_LIMIT} consecutive failures with signature "
                    f"{tail[0]!r}",
                    {"signature": tail[0]},
                )
        total = len(self._outcomes)
        if total >= self.FIRST_WINDOW:
            first = self._outcomes[: self.FIRST_WINDOW]
            rate = sum(first) / self.FIRST_WINDOW
            if rate > self.FIRST_WINDOW_FAILURE_RATE:
                return self._set_trip(
                    "first_window_failure_rate",
                    f"{rate:.0%} of the first {self.FIRST_WINDOW} jobs failed "
                    f"(limit {self.FIRST_WINDOW_FAILURE_RATE:.0%})",
                    {"failure_rate": rate},
                )
        if total >= self.MOVING_WINDOW:
            window = self._outcomes[-self.MOVING_WINDOW :]
            rate = sum(window) / self.MOVING_WINDOW
            if rate > self.MOVING_WINDOW_FAILURE_RATE:
                return self._set_trip(
                    "moving_window_failure_rate",
                    f"{rate:.0%} of the last {self.MOVING_WINDOW} jobs failed "
                    f"(limit {self.MOVING_WINDOW_FAILURE_RATE:.0%})",
                    {"failure_rate": rate},
                )
        return None

    def _set_trip(
        self, rule: str, reason: str, detail: Mapping[str, object]
    ) -> CircuitBreakerTrip:
        if self._trip is None:
            self._trip = CircuitBreakerTrip(
                model_key=self.model_key, rule=rule, reason=reason, detail=dict(detail)
            )
        return self._trip


@dataclass(frozen=True, slots=True)
class IdleDecision:
    worker_id: str
    shutdown: bool
    reason: str
    grace_seconds: float


def idle_grace_seconds(
    model_key: str, registry_grace_seconds: float | None, *, large_model: bool = False
) -> float:
    """Section 15.11: 5-10 min for small warm models, registry value for huge ones."""

    if registry_grace_seconds is not None:
        if registry_grace_seconds <= 0:
            raise ValueError(f"idle grace for {model_key} must be positive")
        return registry_grace_seconds
    return LARGE_MODEL_IDLE_GRACE_SECONDS if large_model else SMALL_MODEL_IDLE_GRACE_SECONDS


def idle_killer(
    worker: WorkerObservation,
    *,
    queue_empty: bool,
    reserved_shards: int,
    grace_seconds: float,
) -> IdleDecision:
    """All three section 15.11 conditions must hold before a worker is killed."""

    if worker.state == "BUSY":
        return IdleDecision(worker.worker_id, False, "worker is running a page", grace_seconds)
    if not queue_empty:
        return IdleDecision(
            worker.worker_id, False, "queue still has dispatchable jobs", grace_seconds
        )
    if reserved_shards > 0:
        return IdleDecision(
            worker.worker_id, False, f"{reserved_shards} shard(s) still reserved", grace_seconds
        )
    if worker.idle_seconds <= grace_seconds:
        return IdleDecision(
            worker.worker_id,
            False,
            f"idle {worker.idle_seconds:.0f}s is inside the {grace_seconds:.0f}s grace",
            grace_seconds,
        )
    return IdleDecision(
        worker.worker_id,
        True,
        f"queue empty, no reserved shard, idle {worker.idle_seconds:.0f}s > "
        f"{grace_seconds:.0f}s grace",
        grace_seconds,
    )


def lifetime_expiry(
    worker: WorkerObservation,
    *,
    now: datetime,
    max_lifetime_seconds: float = MAX_POD_LIFETIME_SECONDS,
) -> Finding | None:
    """Section 15.12: an experiment pod has a maximum age; orphans do not exist."""

    provisioned = _parse_iso(worker.pod_provisioned_at)
    if provisioned is None:
        return None
    age = (now - provisioned).total_seconds()
    if age <= max_lifetime_seconds:
        return None
    return Finding(
        kind="max_lifetime",
        entity_kind="worker",
        entity_id=worker.worker_id,
        action="drain_then_terminate",
        reason=f"pod age {age / 3600:.1f}h exceeds the {max_lifetime_seconds / 3600:.1f}h maximum",
        detail={"age_seconds": age},
    )


@dataclass(frozen=True, slots=True)
class BudgetAssessment:
    state: str
    projected_usd: float
    spent_usd: float
    committed_usd: float
    soft_cap_usd: float
    hard_cap_usd: float
    allow_new_replicas: bool
    pause_queue: bool
    drain_workers: bool
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "projected_usd": round(self.projected_usd, 4),
            "spent_usd": round(self.spent_usd, 4),
            "committed_usd": round(self.committed_usd, 4),
            "soft_cap_usd": self.soft_cap_usd,
            "hard_cap_usd": self.hard_cap_usd,
            "allow_new_replicas": self.allow_new_replicas,
            "pause_queue": self.pause_queue,
            "drain_workers": self.drain_workers,
            "reason": self.reason,
        }


class BudgetWatchdog:
    """Section 15.13, evaluated every 60 seconds.

    ``projected = spent + (running workers x rate x seconds to next checkpoint)``.
    Soft cap forbids new replicas. Hard cap pauses the queue and drains --
    it never kills a page mid-inference, because the page is the thing that was
    already paid for.
    """

    INTERVAL_SECONDS: Final = 60

    def __init__(
        self,
        *,
        soft_cap_usd: float = BUDGET_SOFT_CAP_USD,
        hard_cap_usd: float = BUDGET_HARD_CAP_USD,
    ) -> None:
        if soft_cap_usd <= 0 or hard_cap_usd <= 0:
            raise ValueError("budget caps must be positive")
        if soft_cap_usd > hard_cap_usd:
            raise ValueError("the soft cap cannot exceed the hard cap")
        self.soft_cap_usd = soft_cap_usd
        self.hard_cap_usd = hard_cap_usd

    def evaluate(
        self,
        *,
        spent_usd: float,
        running_worker_rates_usd_per_hour: Sequence[float],
        seconds_to_next_checkpoint: float,
    ) -> BudgetAssessment:
        if spent_usd < 0:
            raise ValueError("spend cannot be negative")
        if seconds_to_next_checkpoint < 0:
            raise ValueError("time to the next checkpoint cannot be negative")
        committed = (
            sum(running_worker_rates_usd_per_hour) * seconds_to_next_checkpoint / 3600.0
        )
        projected = spent_usd + committed
        if projected >= self.hard_cap_usd:
            return BudgetAssessment(
                state="HARD_CAP",
                projected_usd=projected,
                spent_usd=spent_usd,
                committed_usd=committed,
                soft_cap_usd=self.soft_cap_usd,
                hard_cap_usd=self.hard_cap_usd,
                allow_new_replicas=False,
                pause_queue=True,
                drain_workers=True,
                reason=(
                    f"projected ${projected:.2f} reaches the ${self.hard_cap_usd:.2f} hard cap: "
                    "pause the queue and drain to the next checkpoint without killing a page"
                ),
            )
        if projected >= self.soft_cap_usd:
            return BudgetAssessment(
                state="SOFT_CAP",
                projected_usd=projected,
                spent_usd=spent_usd,
                committed_usd=committed,
                soft_cap_usd=self.soft_cap_usd,
                hard_cap_usd=self.hard_cap_usd,
                allow_new_replicas=False,
                pause_queue=False,
                drain_workers=False,
                reason=(
                    f"projected ${projected:.2f} reaches the ${self.soft_cap_usd:.2f} soft cap: "
                    "no new replicas, running work continues"
                ),
            )
        return BudgetAssessment(
            state="NORMAL",
            projected_usd=projected,
            spent_usd=spent_usd,
            committed_usd=committed,
            soft_cap_usd=self.soft_cap_usd,
            hard_cap_usd=self.hard_cap_usd,
            allow_new_replicas=True,
            pause_queue=False,
            drain_workers=False,
            reason=f"projected ${projected:.2f} is below the ${self.soft_cap_usd:.2f} soft cap",
        )
