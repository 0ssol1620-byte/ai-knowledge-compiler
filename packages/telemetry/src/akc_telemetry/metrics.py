"""Low-cardinality Prometheus metrics for the control plane and workers."""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from wsgiref.simple_server import WSGIServer

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter(
    "akc_http_requests_total",
    "HTTP requests by method, route template, and status class.",
    ("method", "route", "status_class"),
    registry=REGISTRY,
)
HTTP_DURATION = Histogram(
    "akc_http_request_duration_seconds",
    "HTTP request duration by method and route template.",
    ("method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    registry=REGISTRY,
)
JOBS_TERMINAL = Counter(
    "akc_jobs_terminal_total",
    "Jobs entering a terminal status.",
    ("status",),
    registry=REGISTRY,
)
PAGES_TERMINAL = Counter(
    "akc_pages_terminal_total",
    "Pages entering a terminal status by bounded route.",
    ("status", "route"),
    registry=REGISTRY,
)
QUEUE_DEPTH = Gauge(
    "akc_queue_depth",
    "Current processing queue depth by bounded status.",
    ("status",),
    registry=REGISTRY,
)
QUEUE_OLDEST_AGE = Gauge(
    "akc_queue_oldest_job_age_seconds",
    "Age of the oldest queued processing job.",
    registry=REGISTRY,
)
DLQ_MESSAGES = Gauge(
    "akc_dlq_messages",
    "Current dead-letter item count.",
    registry=REGISTRY,
)
SCANNER_UP = Gauge(
    "akc_scanner_up",
    "Whether the fail-closed malware scanner most recently responded.",
    registry=REGISTRY,
)
PROVIDER_UP = Gauge(
    "akc_provider_up",
    "Whether a bounded provider most recently completed successfully.",
    ("provider",),
    registry=REGISTRY,
)
PROVIDER_REQUESTS = Counter(
    "akc_provider_requests_total",
    "Provider calls by bounded provider and result.",
    ("provider", "result"),
    registry=REGISTRY,
)
PROVIDER_COLD_START = Histogram(
    "akc_provider_cold_start_seconds",
    "Provider cold-start duration when supplied by a provider adapter.",
    ("provider",),
    buckets=(0.5, 1, 2.5, 5, 10, 20, 30, 60, 120, 300),
    registry=REGISTRY,
)
PROVIDER_ESTIMATED_COST = Counter(
    "akc_provider_estimated_cost_usd_total",
    "Provider-estimated cost in USD; never inferred from credits.",
    ("provider",),
    registry=REGISTRY,
)
PROVIDER_REVISION_MISMATCH = Counter(
    "akc_provider_revision_mismatch_total",
    "Provider responses rejected for an unexpected immutable revision.",
    ("provider",),
    registry=REGISTRY,
)
CREDIT_ENTRIES = Counter(
    "akc_credit_entries_total",
    "Committed credit ledger entries by bounded type.",
    ("entry_type",),
    registry=REGISTRY,
)
CREDIT_AMOUNT = Counter(
    "akc_credit_amount_total",
    "Committed credit amount by bounded ledger type.",
    ("entry_type",),
    registry=REGISTRY,
)
CREDIT_DUPLICATE_CONSUME = Counter(
    "akc_credit_duplicate_consume_total",
    "Detected duplicate consume attempts that did not create a second charge.",
    registry=REGISTRY,
)
UNSUPPORTED_CLAIM = Counter(
    "akc_unsupported_claim_total",
    "Unsupported knowledge claims by whether they reached an accepted result.",
    ("accepted",),
    registry=REGISTRY,
)
SECURITY_CROSS_TENANT_DENIED = Counter(
    "akc_security_cross_tenant_denied_total",
    "Explicitly detected cross-tenant authorization violations.",
    registry=REGISTRY,
)
AUDIT_WRITE_FAILURE = Counter(
    "akc_audit_write_failure_total",
    "Audit writes that failed to commit.",
    registry=REGISTRY,
)
EXTERNAL_EGRESS_DENIED = Counter(
    "akc_external_egress_denied_total",
    "External provider calls denied by the local privacy policy.",
    registry=REGISTRY,
)
ABUSE_CONTROL_DECISIONS = Counter(
    "akc_abuse_control_decisions_total",
    "Privacy-safe abuse-control decisions by bounded control and result.",
    ("control", "result"),
    registry=REGISTRY,
)
DELETION_OLDEST_PENDING = Gauge(
    "akc_deletion_oldest_pending_seconds",
    "Age of the oldest persisted deletion request, or zero when none exist.",
    registry=REGISTRY,
)
DELETION_ATTEMPTS = Counter(
    "akc_deletion_attempts_total",
    "Deletion lifecycle attempts by bounded terminal result.",
    ("result",),
    registry=REGISTRY,
)
DELETION_OBJECT_RESULTS = Counter(
    "akc_deletion_object_results_total",
    "Object purge operations by bounded result.",
    ("result",),
    registry=REGISTRY,
)
PRODUCT_ANALYTICS_SNAPSHOTS = Counter(
    "akc_product_analytics_snapshots_total",
    "Tenant-local product analytics snapshot requests by bounded result.",
    ("result",),
    registry=REGISTRY,
)
PRODUCT_ANALYTICS_EVENTS = Counter(
    "akc_product_analytics_events_total",
    "Allowlisted product analytics events by type and bounded storage result.",
    ("event_type", "result"),
    registry=REGISTRY,
)
COLLECTION_ESTIMATE_CREDIT_ERROR_RATIO = Histogram(
    "akc_collection_estimate_credit_error_ratio",
    "Absolute P50 credit estimate error divided by actual credits.",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1, 2, 5),
    registry=REGISTRY,
)
COLLECTION_ESTIMATE_DURATION_ERROR_RATIO = Histogram(
    "akc_collection_estimate_duration_error_ratio",
    "Absolute P50 duration estimate error divided by actual duration.",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1, 2, 5),
    registry=REGISTRY,
)
COLLECTION_ROUTE_MIX_ERROR_RATIO = Histogram(
    "akc_collection_route_mix_error_ratio",
    "Total-variation distance between predicted and completed route mix.",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1),
    registry=REGISTRY,
)
COLLECTION_RETRY_RATIO = Histogram(
    "akc_collection_retry_ratio",
    "Observed retry attempts divided by completed processing units.",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1, 2, 5),
    registry=REGISTRY,
)
COLLECTION_GPU_SECONDS = Counter(
    "akc_collection_gpu_seconds_total",
    "Provider-reported GPU seconds accepted from verified result manifests.",
    registry=REGISTRY,
)
COLLECTION_KNOWLEDGE_TOKENS = Counter(
    "akc_collection_knowledge_tokens_total",
    "Measured knowledge pipeline tokens by bounded stage.",
    ("stage",),
    registry=REGISTRY,
)
COLLECTION_EXPORT_SECONDS = Histogram(
    "akc_collection_export_duration_seconds",
    "Committed collection export duration by bounded profile.",
    ("profile",),
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 900),
    registry=REGISTRY,
)
COLLECTION_STORAGE_AMPLIFICATION_RATIO = Histogram(
    "akc_collection_storage_amplification_ratio",
    "Completed package bytes divided by unique verified source bytes.",
    buckets=(0.05, 0.1, 0.25, 0.5, 0.75, 1, 1.2, 1.5, 2, 2.5, 5, 10, 25),
    registry=REGISTRY,
)
COLLECTION_CREDITS_REFUNDED = Counter(
    "akc_collection_credits_refunded_total",
    "Credits actually refunded while settling collection processing.",
    registry=REGISTRY,
)

_SAFE_ROUTE = re.compile(r"^/[A-Za-z0-9_./{}:-]{0,240}$")
_UUID_SEGMENT = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_LONG_NUMBER_SEGMENT = re.compile(r"^[0-9]{6,}$")
_OPAQUE_SEGMENT = re.compile(r"^[A-Za-z0-9_-]{24,}$")
_PROVIDERS = frozenset(
    {
        "deterministic",
        "external",
        "mock",
        "paddleocr_vl_1_6",
        "qwen3_5_4b",
        "runpod",
    }
)
_ROUTES = frozenset({"native", "visual", "precision", "unknown"})
_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})
_PAGE_STATUSES = frozenset({"completed", "failed", "quarantined", "unresolved"})
_CREDIT_TYPES = frozenset({"grant", "reserve", "consume", "release", "refund", "expire", "adjust"})
_ABUSE_CONTROLS = frozenset(
    {
        "analyze",
        "billing",
        "captcha",
        "compile",
        "duplicate_hash",
        "email_resend",
        "email_verify",
        "export",
        "free_file_cap",
        "free_gpu_cap",
        "free_page_cap",
        "login",
        "payment_webhook",
        "registration",
        "upload",
    }
)
_ABUSE_RESULTS = frozenset(
    {
        "allowed",
        "capped",
        "dead_letter",
        "delivered",
        "duplicate",
        "expired",
        "invalid",
        "ignored",
        "limited",
        "processed",
        "rejected",
        "replay",
        "required",
        "retry",
        "unavailable",
        "verified",
    }
)
_PRODUCT_ANALYTICS_EVENT_TYPES = frozenset(
    {
        "estimate_viewed",
        "project_revisited",
        "result_first_viewed",
        "source_merged",
        "support_session_closed",
        "user_reported_error",
    }
)
_PRODUCT_ANALYTICS_EVENT_RESULTS = frozenset({"stored", "opted_out", "private_mode", "rejected"})
_PRODUCT_ANALYTICS_SNAPSHOT_RESULTS = frozenset({"enabled", "disabled", "failed"})
_KNOWLEDGE_TOKEN_STAGES = frozenset({"probe", "compile", "export"})
_COLLECTION_EXPORT_PROFILES = frozenset({"complete_knowledge", "repository_manifest"})


def _bounded(value: object, allowed: frozenset[str], fallback: str = "other") -> str:
    normalized = str(value).strip().casefold()
    return normalized if normalized in allowed else fallback


def safe_route_template(value: object) -> str:
    """Return only framework route templates, never the concrete request path."""

    route = str(value or "").strip()
    if not route or not _SAFE_ROUTE.fullmatch(route):
        return "unmatched"
    for segment in route.split("/"):
        if not segment or ("{" in segment and "}" in segment):
            continue
        if (
            "@" in segment
            or "%" in segment
            or _UUID_SEGMENT.fullmatch(segment)
            or _LONG_NUMBER_SEGMENT.fullmatch(segment)
            or _OPAQUE_SEGMENT.fullmatch(segment)
        ):
            return "unmatched"
    return route


def observe_http(
    *,
    method: str,
    route_template: object,
    status_code: int,
    duration_seconds: float,
) -> None:
    method_label = (
        method.upper()
        if method.upper()
        in {
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "HEAD",
            "OPTIONS",
        }
        else "OTHER"
    )
    route = safe_route_template(route_template)
    status_class = f"{max(1, min(5, int(status_code) // 100))}xx"
    HTTP_REQUESTS.labels(method_label, route, status_class).inc()
    HTTP_DURATION.labels(method_label, route).observe(max(0.0, duration_seconds))


def record_job_terminal(status: str) -> None:
    JOBS_TERMINAL.labels(_bounded(status, _JOB_STATUSES)).inc()


def record_page_terminal(status: str, route: str | None) -> None:
    PAGES_TERMINAL.labels(
        _bounded(status, _PAGE_STATUSES),
        _bounded(route or "unknown", _ROUTES, "unknown"),
    ).inc()


def record_provider_request(provider: str, *, result: str) -> None:
    provider_label = _bounded(provider, _PROVIDERS)
    result_label = _bounded(
        result,
        frozenset({"success", "failed", "denied", "revision_mismatch"}),
    )
    PROVIDER_REQUESTS.labels(provider_label, result_label).inc()
    PROVIDER_UP.labels(provider_label).set(1 if result_label == "success" else 0)


def set_provider_up(provider: str, *, up: bool) -> None:
    PROVIDER_UP.labels(_bounded(provider, _PROVIDERS)).set(1 if up else 0)


def observe_provider_cold_start(provider: str, seconds: float) -> None:
    PROVIDER_COLD_START.labels(_bounded(provider, _PROVIDERS)).observe(max(0.0, seconds))


def record_provider_cost(provider: str, amount_usd: Decimal | float | str) -> None:
    amount = Decimal(str(amount_usd))
    if amount.is_finite() and amount >= 0:
        PROVIDER_ESTIMATED_COST.labels(_bounded(provider, _PROVIDERS)).inc(float(amount))


def record_provider_revision_mismatch(provider: str) -> None:
    provider_label = _bounded(provider, _PROVIDERS)
    PROVIDER_REVISION_MISMATCH.labels(provider_label).inc()
    record_provider_request(provider_label, result="revision_mismatch")


def record_credit_entry(entry_type: str, amount: Decimal | float | str) -> None:
    entry_label = _bounded(entry_type, _CREDIT_TYPES)
    numeric = Decimal(str(amount))
    if not numeric.is_finite() or numeric <= 0:
        return
    CREDIT_ENTRIES.labels(entry_label).inc()
    CREDIT_AMOUNT.labels(entry_label).inc(float(numeric))


def record_credit_duplicate_consume() -> None:
    CREDIT_DUPLICATE_CONSUME.inc()


def record_unsupported_claim(*, accepted: bool) -> None:
    UNSUPPORTED_CLAIM.labels("true" if accepted else "false").inc()


def record_external_egress_denied() -> None:
    EXTERNAL_EGRESS_DENIED.inc()


def record_abuse_control_decision(*, control: str, result: str) -> None:
    """Record a bounded decision without customer, network, or token labels."""

    ABUSE_CONTROL_DECISIONS.labels(
        _bounded(control, _ABUSE_CONTROLS),
        _bounded(result, _ABUSE_RESULTS),
    ).inc()


def set_queue_gauges(
    *,
    queue_counts: Mapping[str, int],
    oldest_queue_age_seconds: float,
) -> None:
    for status in ("queued", "running", "paused", "waiting_review"):
        QUEUE_DEPTH.labels(status).set(max(0, int(queue_counts.get(status, 0))))
    QUEUE_OLDEST_AGE.set(max(0.0, oldest_queue_age_seconds))


def set_dead_letter_count(count: int) -> None:
    DLQ_MESSAGES.set(max(0, count))


def set_deletion_oldest_pending(seconds: float) -> None:
    DELETION_OLDEST_PENDING.set(max(0.0, seconds))


def record_deletion_attempt(result: str) -> None:
    bounded = result if result in {"purged", "retry", "dead_letter", "busy"} else "unknown"
    DELETION_ATTEMPTS.labels(bounded).inc()


def record_deletion_object_result(result: str) -> None:
    bounded = result if result in {"purged", "retry"} else "unknown"
    DELETION_OBJECT_RESULTS.labels(bounded).inc()


def record_product_analytics_snapshot(result: str) -> None:
    """Record only contract state, never a tenant, actor, or requested window."""

    PRODUCT_ANALYTICS_SNAPSHOTS.labels(_bounded(result, _PRODUCT_ANALYTICS_SNAPSHOT_RESULTS)).inc()


def record_product_analytics_event(event_type: str, *, result: str) -> None:
    """Record an allowlisted event outcome with fixed-cardinality labels."""

    PRODUCT_ANALYTICS_EVENTS.labels(
        _bounded(event_type, _PRODUCT_ANALYTICS_EVENT_TYPES),
        _bounded(result, _PRODUCT_ANALYTICS_EVENT_RESULTS),
    ).inc()


def _nonnegative_metric(value: Decimal | float | int | str) -> float | None:
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not numeric.is_finite() or numeric < 0:
        return None
    return float(numeric)


def observe_collection_estimate_calibration(
    *,
    credit_error_ratio: Decimal | float | str | None = None,
    duration_error_ratio: Decimal | float | str | None = None,
    route_mix_error_ratio: Decimal | float | str | None = None,
) -> None:
    """Observe only ratios derived from committed estimates and actual outcomes."""

    for metric, value in (
        (COLLECTION_ESTIMATE_CREDIT_ERROR_RATIO, credit_error_ratio),
        (COLLECTION_ESTIMATE_DURATION_ERROR_RATIO, duration_error_ratio),
        (COLLECTION_ROUTE_MIX_ERROR_RATIO, route_mix_error_ratio),
    ):
        if value is None:
            continue
        numeric = _nonnegative_metric(value)
        if numeric is not None:
            metric.observe(numeric)


def observe_collection_retry_ratio(value: Decimal | float | str) -> None:
    numeric = _nonnegative_metric(value)
    if numeric is not None:
        COLLECTION_RETRY_RATIO.observe(numeric)


def record_collection_gpu_seconds(value: Decimal | float | str) -> None:
    numeric = _nonnegative_metric(value)
    if numeric is not None and numeric > 0:
        COLLECTION_GPU_SECONDS.inc(numeric)


def record_collection_knowledge_tokens(*, stage: str, tokens: int) -> None:
    if tokens <= 0:
        return
    COLLECTION_KNOWLEDGE_TOKENS.labels(
        _bounded(stage, _KNOWLEDGE_TOKEN_STAGES)
    ).inc(tokens)


def observe_collection_export(
    *,
    profile: str,
    duration_seconds: Decimal | float | str,
    storage_amplification_ratio: Decimal | float | str | None = None,
) -> None:
    duration = _nonnegative_metric(duration_seconds)
    if duration is not None:
        COLLECTION_EXPORT_SECONDS.labels(
            _bounded(profile, _COLLECTION_EXPORT_PROFILES)
        ).observe(duration)
    if storage_amplification_ratio is not None:
        ratio = _nonnegative_metric(storage_amplification_ratio)
        if ratio is not None:
            COLLECTION_STORAGE_AMPLIFICATION_RATIO.observe(ratio)


def record_collection_credits_refunded(value: Decimal | float | str) -> None:
    numeric = _nonnegative_metric(value)
    if numeric is not None and numeric > 0:
        COLLECTION_CREDITS_REFUNDED.inc(numeric)


def set_runtime_gauges(
    *,
    queue_counts: Mapping[str, int],
    oldest_queue_age_seconds: float,
    dead_letter_count: int,
    scanner_up: bool | None = None,
    deletion_oldest_pending_seconds: float = 0,
) -> None:
    set_queue_gauges(
        queue_counts=queue_counts,
        oldest_queue_age_seconds=oldest_queue_age_seconds,
    )
    set_dead_letter_count(dead_letter_count)
    set_deletion_oldest_pending(deletion_oldest_pending_seconds)
    if scanner_up is not None:
        SCANNER_UP.set(1 if scanner_up else 0)


def render_prometheus() -> bytes:
    return generate_latest(REGISTRY)


@dataclass(frozen=True, slots=True)
class MetricsHttpServer:
    """Handle for the scheduler's private Prometheus endpoint."""

    server: WSGIServer
    thread: threading.Thread

    def shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def start_metrics_http_server(*, port: int, addr: str) -> MetricsHttpServer:
    """Start a content-free metrics endpoint on an explicitly configured bind."""

    server, thread = start_http_server(port=port, addr=addr, registry=REGISTRY)
    return MetricsHttpServer(server=server, thread=thread)


def _initialize_contract_series() -> None:
    HTTP_REQUESTS.labels("GET", "/metrics", "2xx").inc(0)
    HTTP_DURATION.labels("GET", "/metrics")
    for status in sorted(_JOB_STATUSES):
        JOBS_TERMINAL.labels(status).inc(0)
    for status in sorted(_PAGE_STATUSES):
        for route in sorted(_ROUTES):
            PAGES_TERMINAL.labels(status, route).inc(0)
    for status in ("queued", "running", "paused", "waiting_review"):
        QUEUE_DEPTH.labels(status).set(0)
    for provider in sorted(_PROVIDERS):
        PROVIDER_COLD_START.labels(provider)
        PROVIDER_ESTIMATED_COST.labels(provider).inc(0)
        PROVIDER_REVISION_MISMATCH.labels(provider).inc(0)
        for result in ("success", "failed", "denied", "revision_mismatch"):
            PROVIDER_REQUESTS.labels(provider, result).inc(0)
    for entry_type in sorted(_CREDIT_TYPES):
        CREDIT_ENTRIES.labels(entry_type).inc(0)
        CREDIT_AMOUNT.labels(entry_type).inc(0)
    for accepted in ("true", "false"):
        UNSUPPORTED_CLAIM.labels(accepted).inc(0)
    for control in sorted(_ABUSE_CONTROLS):
        for result in sorted(_ABUSE_RESULTS):
            ABUSE_CONTROL_DECISIONS.labels(control, result).inc(0)
    for result in sorted(_PRODUCT_ANALYTICS_SNAPSHOT_RESULTS):
        PRODUCT_ANALYTICS_SNAPSHOTS.labels(result).inc(0)
    for event_type in sorted(_PRODUCT_ANALYTICS_EVENT_TYPES):
        for result in sorted(_PRODUCT_ANALYTICS_EVENT_RESULTS):
            PRODUCT_ANALYTICS_EVENTS.labels(event_type, result).inc(0)
    for stage in sorted(_KNOWLEDGE_TOKEN_STAGES):
        COLLECTION_KNOWLEDGE_TOKENS.labels(stage).inc(0)
    for profile in sorted(_COLLECTION_EXPORT_PROFILES):
        COLLECTION_EXPORT_SECONDS.labels(profile)
    QUEUE_OLDEST_AGE.set(0)
    DLQ_MESSAGES.set(0)
    DELETION_OLDEST_PENDING.set(0)
    SECURITY_CROSS_TENANT_DENIED.inc(0)
    AUDIT_WRITE_FAILURE.inc(0)
    CREDIT_DUPLICATE_CONSUME.inc(0)
    EXTERNAL_EGRESS_DENIED.inc(0)


_initialize_contract_series()
