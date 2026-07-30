"""Bounded-cardinality metrics for durable URL ingestion."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

URL_FETCH_ATTEMPTS = Counter(
    "akc_url_fetch_attempts_total",
    "URL ingestion attempts by terminal attempt outcome.",
    ["result"],
)
URL_FETCH_DURATION = Histogram(
    "akc_url_fetch_attempt_duration_seconds",
    "End-to-end URL fetch attempt latency.",
)
URL_FETCH_QUEUE_DEPTH = Gauge(
    "akc_url_fetch_queue_depth",
    "Durable URL tasks by active status.",
    ["status"],
)
URL_FETCH_DLQ = Gauge(
    "akc_url_fetch_dead_letter_tasks",
    "URL tasks currently in the dead-letter state.",
)

_RESULTS = frozenset(
    {
        "completed",
        "retry",
        "failed",
        "dead_letter",
        "cancelled",
        "stale",
    }
)


def record_url_fetch_attempt(result: str) -> None:
    if result not in _RESULTS:
        raise ValueError("unsupported URL fetch attempt result")
    URL_FETCH_ATTEMPTS.labels(result=result).inc()
