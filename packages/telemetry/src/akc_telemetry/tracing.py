"""Privacy-safe OpenTelemetry wiring for FastAPI."""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer

from .metrics import observe_http, safe_route_template

_SERVICE_NAME = re.compile(r"^[a-z][a-z0-9-]{1,62}$")


@dataclass
class TelemetryRuntime:
    tracer_provider: TracerProvider | None
    tracer: Tracer | None

    def shutdown(self) -> None:
        if self.tracer_provider is not None:
            self.tracer_provider.shutdown()


def _validated_endpoint(value: str) -> tuple[str, bool]:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("OTLP endpoint must be an HTTP(S) origin without credentials")
    return value.rstrip("/"), parsed.scheme == "http"


def create_telemetry_runtime(
    *,
    enabled: bool,
    service_name: str,
    environment: str,
    endpoint: str | None,
    export_timeout_seconds: float,
) -> TelemetryRuntime:
    if not enabled:
        return TelemetryRuntime(tracer_provider=None, tracer=None)
    if not _SERVICE_NAME.fullmatch(service_name):
        raise ValueError("telemetry service name must be a lowercase DNS-style label")
    if not endpoint:
        raise ValueError("enabled telemetry requires an OTLP endpoint")
    safe_endpoint, insecure = _validated_endpoint(endpoint)
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": service_name,
                "deployment.environment.name": environment,
            }
        )
    )
    exporter = OTLPSpanExporter(
        endpoint=safe_endpoint,
        insecure=insecure,
        timeout=export_timeout_seconds,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return TelemetryRuntime(
        tracer_provider=provider,
        tracer=provider.get_tracer("akc.fastapi"),
    )


def install_fastapi_observability(app: FastAPI, runtime: TelemetryRuntime) -> None:
    """Install metrics and spans that use route templates, never concrete paths."""

    @app.middleware("http")
    async def observe_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started = time.perf_counter()
        status_code = 500
        span = (
            runtime.tracer.start_span(
                "HTTP request",
                context=extract(request.headers),
                kind=SpanKind.SERVER,
            )
            if runtime.tracer is not None
            else trace.INVALID_SPAN
        )
        try:
            with trace.use_span(span, end_on_exit=False):
                response = await call_next(request)
                status_code = response.status_code
                return response
        except Exception:
            if span.is_recording():
                span.set_status(Status(StatusCode.ERROR))
            raise
        finally:
            route = safe_route_template(getattr(request.scope.get("route"), "path", None))
            method = request.method.upper()
            if span.is_recording():
                span.update_name(f"{method} {route}")
                span.set_attribute("http.request.method", method)
                span.set_attribute("http.route", route)
                span.set_attribute("http.response.status_code", status_code)
                span.set_status(
                    Status(StatusCode.ERROR if status_code >= 500 else StatusCode.UNSET)
                )
                span.end()
            observe_http(
                method=method,
                route_template=route,
                status_code=status_code,
                duration_seconds=time.perf_counter() - started,
            )
