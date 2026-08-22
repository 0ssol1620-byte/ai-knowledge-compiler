"""Privacy-safe, low-cardinality metrics for the v6 parallel runtime.

All label domains in this module are closed sets.  Runtime, customer, document,
job, shard, attempt, worker, model, and content identifiers are intentionally
absent from the metric contracts.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from prometheus_client import Counter, Histogram

from .metrics import REGISTRY

PARALLEL_SHARDS_TERMINAL = Counter(
    "akc_parallel_shards_terminal_total",
    "Parallel shards entering a terminal status.",
    ("status",),
    registry=REGISTRY,
)
PARALLEL_ATTEMPTS_TERMINAL = Counter(
    "akc_parallel_attempts_terminal_total",
    "Parallel parse attempts entering a terminal status.",
    ("status",),
    registry=REGISTRY,
)
PARALLEL_VALIDATIONS = Counter(
    "akc_parallel_validations_total",
    "Committed parallel validation receipts by fixed L0-L6 level and outcome.",
    ("level", "outcome"),
    registry=REGISTRY,
)
PARALLEL_WORKER_HEALTH_TRANSITIONS = Counter(
    "akc_parallel_worker_health_transitions_total",
    "Worker health transitions by independent infrastructure or semantic projection.",
    ("projection", "previous", "current"),
    registry=REGISTRY,
)
PARALLEL_RECOVERY_TERMINAL = Counter(
    "akc_parallel_recovery_terminal_total",
    "Selective recovery tasks entering a terminal outcome by bounded recovery level.",
    ("level", "outcome"),
    registry=REGISTRY,
)
PARALLEL_CONTINUITY_OUTCOMES = Counter(
    "akc_parallel_continuity_outcomes_total",
    "Continuity merge outcomes; no document or edge identifiers are labels.",
    ("outcome",),
    registry=REGISTRY,
)
PARALLEL_ACCEPTED_BLOCKS = Counter(
    "akc_parallel_accepted_blocks_total",
    "Committed accepted-block projections by verification state and billing class.",
    ("final_state", "billing"),
    registry=REGISTRY,
)
PARALLEL_NONBILLABLE_ATTEMPTS = Counter(
    "akc_parallel_nonbillable_attempts_total",
    "Terminal attempts explicitly suppressed from billing by bounded disposition.",
    ("disposition",),
    registry=REGISTRY,
)
PARALLEL_DUPLICATE_CREDIT_SUPPRESSIONS = Counter(
    "akc_parallel_duplicate_credit_suppressions_total",
    "Duplicate or losing credit claims suppressed before a second charge.",
    ("reason",),
    registry=REGISTRY,
)
PARALLEL_PROVIDER_OBSERVATIONS = Counter(
    "akc_parallel_provider_observations_total",
    "Accepted provider telemetry observations by bounded provider and measurement.",
    ("provider", "measurement"),
    registry=REGISTRY,
)
PARALLEL_PROVIDER_QUEUE_DELAY = Histogram(
    "akc_parallel_provider_queue_delay_seconds",
    "Provider-reported queue delay for parallel invocations.",
    ("provider",),
    buckets=(0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600),
    registry=REGISTRY,
)
PARALLEL_PROVIDER_EXECUTION_DURATION = Histogram(
    "akc_parallel_provider_execution_duration_seconds",
    "Provider-reported execution duration for parallel invocations.",
    ("provider",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1800),
    registry=REGISTRY,
)
PARALLEL_PROVIDER_JOB_COST = Histogram(
    "akc_parallel_provider_job_cost_usd",
    "Provider-reported USD cost per parallel invocation; never inferred from credits.",
    ("provider",),
    buckets=(0.000001, 0.00001, 0.0001, 0.001, 0.01, 0.05, 0.1, 0.5, 1, 5, 10, 50, 100),
    registry=REGISTRY,
)
PARALLEL_PROVIDER_COST = Counter(
    "akc_parallel_provider_cost_usd_total",
    "Provider-reported USD cost for parallel invocations; never inferred from credits.",
    ("provider",),
    registry=REGISTRY,
)
PARALLEL_PROVIDER_GPU_SECONDS = Counter(
    "akc_parallel_provider_gpu_seconds_total",
    "Provider-reported GPU seconds for parallel invocations.",
    ("provider",),
    registry=REGISTRY,
)

_SHARD_TERMINAL_STATUSES = frozenset(
    {"accepted", "unresolved", "quarantined", "failed", "superseded"}
)
_ATTEMPT_TERMINAL_STATUSES = frozenset(
    {
        "accepted",
        "rejected",
        "retryable_failed",
        "terminal_failed",
        "superseded",
        "quarantined",
    }
)
_VALIDATION_LEVELS = tuple(f"L{level}" for level in range(7))
_VALIDATION_OUTCOMES = frozenset({"passed", "failed", "abstained", "unavailable"})
_INFRASTRUCTURE_STATUSES = frozenset({"healthy", "degraded", "unreachable", "terminated"})
_SEMANTIC_STATUSES = frozenset({"healthy", "degraded", "failing", "unknown"})
_RECOVERY_LEVELS = frozenset({"cell", "row", "table", "region", "page", "page_group"})
_RECOVERY_OUTCOMES = frozenset({"completed", "unresolved", "failed", "cancelled"})
_CONTINUITY_OUTCOMES = frozenset({"accepted", "rejected", "unresolved", "failed"})
_FINAL_STATES = frozenset(
    {
        "verified",
        "authority_verified",
        "cross_model_verified",
        "auto_repaired",
        "unresolved",
        "quarantined",
        "failed",
    }
)
_BILLING_CLASSES = frozenset({"billable", "nonbillable"})
_NONBILLABLE_DISPOSITIONS = frozenset(
    {
        "retry_unbillable",
        "speculative_unbillable",
        "straggler_unbillable",
        "unresolved_unbillable",
        "quarantine_unbillable",
        "shadow_unbillable",
        "refunded",
    }
)
_DUPLICATE_SUPPRESSION_REASONS = frozenset(
    {"idempotent_replay", "duplicate_compute", "non_winner", "ledger_conflict"}
)
_PARALLEL_PROVIDERS = frozenset(
    {"deterministic", "external", "mock", "paddleocr_vl_1_6", "qwen3_5_4b", "runpod"}
)
_PROVIDER_MEASUREMENTS = ("queue_delay", "execution_duration", "job_cost", "gpu_seconds")


def _bounded(value: object, allowed: frozenset[str], fallback: str = "other") -> str:
    normalized = str(value).strip().casefold()
    return normalized if normalized in allowed else fallback


def _validation_level(value: object) -> str:
    if isinstance(value, bool):
        return "other"
    if isinstance(value, int) and 0 <= value <= 6:
        return f"L{value}"
    normalized = str(value).strip().upper()
    return normalized if normalized in _VALIDATION_LEVELS else "other"


def _nonnegative(value: Decimal | float | int | str | None) -> float | None:
    if value is None:
        return None
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not numeric.is_finite() or numeric < 0:
        return None
    return float(numeric)


def record_parallel_shard_terminal(status: object) -> None:
    PARALLEL_SHARDS_TERMINAL.labels(_bounded(status, _SHARD_TERMINAL_STATUSES)).inc()


def record_parallel_attempt_terminal(status: object) -> None:
    PARALLEL_ATTEMPTS_TERMINAL.labels(_bounded(status, _ATTEMPT_TERMINAL_STATUSES)).inc()


def record_parallel_validation(*, level: object, outcome: object) -> None:
    PARALLEL_VALIDATIONS.labels(
        _validation_level(level),
        _bounded(outcome, _VALIDATION_OUTCOMES),
    ).inc()


def record_parallel_worker_dual_health_transition(
    *,
    previous_infrastructure: object,
    current_infrastructure: object,
    previous_semantic: object,
    current_semantic: object,
) -> None:
    """Record changed projections independently; identifiers are never accepted."""

    transitions = (
        (
            "infrastructure",
            _bounded(previous_infrastructure, _INFRASTRUCTURE_STATUSES),
            _bounded(current_infrastructure, _INFRASTRUCTURE_STATUSES),
        ),
        (
            "semantic",
            _bounded(previous_semantic, _SEMANTIC_STATUSES),
            _bounded(current_semantic, _SEMANTIC_STATUSES),
        ),
    )
    for projection, previous, current in transitions:
        if previous != current:
            PARALLEL_WORKER_HEALTH_TRANSITIONS.labels(projection, previous, current).inc()


def record_parallel_recovery_terminal(*, level: object, outcome: object) -> None:
    PARALLEL_RECOVERY_TERMINAL.labels(
        _bounded(level, _RECOVERY_LEVELS),
        _bounded(outcome, _RECOVERY_OUTCOMES),
    ).inc()


def record_parallel_continuity_outcome(outcome: object) -> None:
    PARALLEL_CONTINUITY_OUTCOMES.labels(_bounded(outcome, _CONTINUITY_OUTCOMES)).inc()


def record_parallel_acceptance(*, final_state: object, billable: bool) -> None:
    PARALLEL_ACCEPTED_BLOCKS.labels(
        _bounded(final_state, _FINAL_STATES),
        "billable" if billable else "nonbillable",
    ).inc()


def record_parallel_nonbillable_attempt(disposition: object) -> None:
    PARALLEL_NONBILLABLE_ATTEMPTS.labels(_bounded(disposition, _NONBILLABLE_DISPOSITIONS)).inc()


def record_parallel_duplicate_credit_suppression(reason: object) -> None:
    PARALLEL_DUPLICATE_CREDIT_SUPPRESSIONS.labels(
        _bounded(reason, _DUPLICATE_SUPPRESSION_REASONS)
    ).inc()


def observe_parallel_provider_job(
    *,
    provider: object,
    queue_delay_seconds: Decimal | float | int | str | None = None,
    execution_seconds: Decimal | float | int | str | None = None,
    cost_usd: Decimal | float | int | str | None = None,
    gpu_seconds: Decimal | float | int | str | None = None,
) -> None:
    """Observe only finite, non-negative provider measurements.

    Values must originate in provider receipts.  Cost is deliberately distinct
    from user credits and is not derived from billing ledger entries.
    """

    provider_label = _bounded(provider, _PARALLEL_PROVIDERS)
    observations = (
        (
            "queue_delay",
            _nonnegative(queue_delay_seconds),
            PARALLEL_PROVIDER_QUEUE_DELAY,
        ),
        (
            "execution_duration",
            _nonnegative(execution_seconds),
            PARALLEL_PROVIDER_EXECUTION_DURATION,
        ),
        ("job_cost", _nonnegative(cost_usd), PARALLEL_PROVIDER_JOB_COST),
    )
    for measurement, numeric, histogram in observations:
        if numeric is None:
            continue
        histogram.labels(provider_label).observe(numeric)
        PARALLEL_PROVIDER_OBSERVATIONS.labels(provider_label, measurement).inc()

    cost = _nonnegative(cost_usd)
    if cost is not None:
        PARALLEL_PROVIDER_COST.labels(provider_label).inc(cost)

    gpu = _nonnegative(gpu_seconds)
    if gpu is not None:
        PARALLEL_PROVIDER_GPU_SECONDS.labels(provider_label).inc(gpu)
        PARALLEL_PROVIDER_OBSERVATIONS.labels(provider_label, "gpu_seconds").inc()


def _initialize_contract_series() -> None:
    for status in sorted(_SHARD_TERMINAL_STATUSES):
        PARALLEL_SHARDS_TERMINAL.labels(status).inc(0)
    for status in sorted(_ATTEMPT_TERMINAL_STATUSES):
        PARALLEL_ATTEMPTS_TERMINAL.labels(status).inc(0)
    for level in _VALIDATION_LEVELS:
        for outcome in sorted(_VALIDATION_OUTCOMES):
            PARALLEL_VALIDATIONS.labels(level, outcome).inc(0)
    for projection, statuses in (
        ("infrastructure", _INFRASTRUCTURE_STATUSES),
        ("semantic", _SEMANTIC_STATUSES),
    ):
        for previous in sorted(statuses):
            for current in sorted(statuses):
                if previous != current:
                    PARALLEL_WORKER_HEALTH_TRANSITIONS.labels(projection, previous, current).inc(0)
    for level in sorted(_RECOVERY_LEVELS):
        for outcome in sorted(_RECOVERY_OUTCOMES):
            PARALLEL_RECOVERY_TERMINAL.labels(level, outcome).inc(0)
    for outcome in sorted(_CONTINUITY_OUTCOMES):
        PARALLEL_CONTINUITY_OUTCOMES.labels(outcome).inc(0)
    for final_state in sorted(_FINAL_STATES):
        for billing in sorted(_BILLING_CLASSES):
            PARALLEL_ACCEPTED_BLOCKS.labels(final_state, billing).inc(0)
    for disposition in sorted(_NONBILLABLE_DISPOSITIONS):
        PARALLEL_NONBILLABLE_ATTEMPTS.labels(disposition).inc(0)
    for reason in sorted(_DUPLICATE_SUPPRESSION_REASONS):
        PARALLEL_DUPLICATE_CREDIT_SUPPRESSIONS.labels(reason).inc(0)
    for provider in sorted(_PARALLEL_PROVIDERS):
        PARALLEL_PROVIDER_QUEUE_DELAY.labels(provider)
        PARALLEL_PROVIDER_EXECUTION_DURATION.labels(provider)
        PARALLEL_PROVIDER_JOB_COST.labels(provider)
        PARALLEL_PROVIDER_COST.labels(provider).inc(0)
        PARALLEL_PROVIDER_GPU_SECONDS.labels(provider).inc(0)
        for measurement in _PROVIDER_MEASUREMENTS:
            PARALLEL_PROVIDER_OBSERVATIONS.labels(provider, measurement).inc(0)


_initialize_contract_series()


__all__ = [
    "PARALLEL_ACCEPTED_BLOCKS",
    "PARALLEL_ATTEMPTS_TERMINAL",
    "PARALLEL_CONTINUITY_OUTCOMES",
    "PARALLEL_DUPLICATE_CREDIT_SUPPRESSIONS",
    "PARALLEL_NONBILLABLE_ATTEMPTS",
    "PARALLEL_PROVIDER_COST",
    "PARALLEL_PROVIDER_EXECUTION_DURATION",
    "PARALLEL_PROVIDER_GPU_SECONDS",
    "PARALLEL_PROVIDER_JOB_COST",
    "PARALLEL_PROVIDER_OBSERVATIONS",
    "PARALLEL_PROVIDER_QUEUE_DELAY",
    "PARALLEL_RECOVERY_TERMINAL",
    "PARALLEL_SHARDS_TERMINAL",
    "PARALLEL_VALIDATIONS",
    "PARALLEL_WORKER_HEALTH_TRANSITIONS",
    "observe_parallel_provider_job",
    "record_parallel_acceptance",
    "record_parallel_attempt_terminal",
    "record_parallel_continuity_outcome",
    "record_parallel_duplicate_credit_suppression",
    "record_parallel_nonbillable_attempt",
    "record_parallel_recovery_terminal",
    "record_parallel_shard_terminal",
    "record_parallel_validation",
    "record_parallel_worker_dual_health_transition",
]
