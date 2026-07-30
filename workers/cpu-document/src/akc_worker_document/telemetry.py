"""Low-cardinality analysis worker metrics."""

from __future__ import annotations

from akc_telemetry.metrics import REGISTRY
from prometheus_client import Counter, Gauge, Histogram

ANALYSIS_ATTEMPTS = Counter(
    "akc_analysis_attempts_total",
    "Native analysis attempts by bounded result.",
    ("result",),
    registry=REGISTRY,
)
ANALYSIS_DURATION = Histogram(
    "akc_analysis_attempt_duration_seconds",
    "End-to-end native analysis attempt duration.",
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
    registry=REGISTRY,
)
ANALYSIS_QUEUE_DEPTH = Gauge(
    "akc_analysis_queue_depth",
    "Current durable analysis task count by bounded status.",
    ("status",),
    registry=REGISTRY,
)
ANALYSIS_DLQ = Gauge(
    "akc_analysis_dead_letter_tasks",
    "Current terminal analysis dead-letter count.",
    registry=REGISTRY,
)
ANALYSIS_SANDBOX_TERMINATIONS = Counter(
    "akc_analysis_sandbox_terminations_total",
    "Parser subprocess terminations by bounded reason.",
    ("reason",),
    registry=REGISTRY,
)
ANALYSIS_PREVIEWS = Counter(
    "akc_analysis_previews_total",
    "Preview outcomes without document or tenant labels.",
    ("result",),
    registry=REGISTRY,
)

_RESULTS = frozenset({"completed", "retry", "dead_letter", "stale"})
_TERMINATIONS = frozenset({"timeout", "crash", "oversize"})
_PREVIEW_RESULTS = frozenset({"available", "unavailable"})


def record_attempt(result: str) -> None:
    ANALYSIS_ATTEMPTS.labels(result if result in _RESULTS else "other").inc()


def record_sandbox_termination(reason: str) -> None:
    ANALYSIS_SANDBOX_TERMINATIONS.labels(reason if reason in _TERMINATIONS else "other").inc()


def record_preview(*, available: bool) -> None:
    result = "available" if available else "unavailable"
    ANALYSIS_PREVIEWS.labels(result if result in _PREVIEW_RESULTS else "unavailable").inc()


def initialize_metrics() -> None:
    for status in ("queued", "running"):
        ANALYSIS_QUEUE_DEPTH.labels(status).set(0)
    ANALYSIS_DLQ.set(0)
    for result in _RESULTS:
        ANALYSIS_ATTEMPTS.labels(result).inc(0)
    for reason in _TERMINATIONS:
        ANALYSIS_SANDBOX_TERMINATIONS.labels(reason).inc(0)
    for result in _PREVIEW_RESULTS:
        ANALYSIS_PREVIEWS.labels(result).inc(0)


initialize_metrics()
