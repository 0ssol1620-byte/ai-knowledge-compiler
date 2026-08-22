from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from akc_api.settings import Settings
from akc_api.telemetry import after_commit_metric, track_audit_write
from akc_telemetry import (
    ABUSE_CONTROL_DECISIONS,
    AUDIT_WRITE_FAILURE,
    PRODUCT_ANALYTICS_EVENTS,
    PRODUCT_ANALYTICS_SNAPSHOTS,
    REDACTED,
    SCANNER_UP,
    TelemetryRuntime,
    contains_obvious_secret,
    create_telemetry_runtime,
    install_fastapi_observability,
    observe_collection_estimate_calibration,
    observe_collection_export,
    observe_collection_retry_ratio,
    record_abuse_control_decision,
    record_collection_credits_refunded,
    record_collection_gpu_seconds,
    record_collection_knowledge_tokens,
    record_product_analytics_event,
    record_product_analytics_snapshot,
    redact_telemetry,
    render_prometheus,
)
from akc_telemetry.metrics import safe_route_template
from fastapi import FastAPI
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def test_redaction_removes_body_secret_filename_and_pii() -> None:
    source = {
        "tenantId": "tenant_001",
        "documentId": "doc_001",
        "sourceFilename": "홍길동 계약서.pdf",
        "rawText": "customer@example.com",
        "authorization": "Bearer abcdefghijklmnop",
        "route": "paddle_vl",
        "tokenCount": 123,
        "contentHash": "sha256:abc",
    }
    result = redact_telemetry(source, pseudonym_key=b"test-key")
    assert result["rawText"] == REDACTED
    assert result["authorization"] == REDACTED
    assert result["sourceFilename"] == "[FILENAME]"
    assert result["tenantId"].startswith("id_")
    assert result["tokenCount"] == 123
    assert result["contentHash"] == "sha256:abc"
    assert not contains_obvious_secret(result)


def test_prometheus_contract_is_present_and_route_labels_fail_closed() -> None:
    concrete_id = str(uuid.uuid4())
    assert safe_route_template("/v1/jobs/{job_id}") == "/v1/jobs/{job_id}"
    assert safe_route_template(f"/v1/jobs/{concrete_id}") == "unmatched"
    assert safe_route_template("/v1/accounts/customer@example.com") == "unmatched"
    assert safe_route_template("/v1/jobs/123456789") == "unmatched"

    SCANNER_UP.set(1)
    payload = render_prometheus().decode("utf-8")
    for series in (
        "akc_audit_write_failure_total",
        "akc_abuse_control_decisions_total",
        "akc_credit_duplicate_consume_total",
        "akc_deletion_oldest_pending_seconds",
        "akc_dlq_messages",
        "akc_external_egress_denied_total",
        "akc_jobs_terminal_total",
        "akc_queue_oldest_job_age_seconds",
        "akc_scanner_up",
        "akc_security_cross_tenant_denied_total",
        "akc_unsupported_claim_total",
    ):
        assert series in payload
    assert concrete_id not in payload
    assert "customer@example.com" not in payload


async def test_fastapi_spans_use_route_templates_without_request_identifiers() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    runtime = TelemetryRuntime(
        tracer_provider=provider,
        tracer=provider.get_tracer("test.fastapi"),
    )
    app = FastAPI()
    install_fastapi_observability(app, runtime)

    @app.get("/v1/items/{item_id}")
    async def item(item_id: uuid.UUID) -> dict[str, str]:
        return {"id": str(item_id)}

    concrete_id = str(uuid.uuid4())
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                f"/v1/items/{concrete_id}",
                params={"email": "customer@example.com"},
            )
        assert response.status_code == 200
        span = exporter.get_finished_spans()[-1]
        assert span.name == "GET /v1/items/{item_id}"
        assert span.attributes == {
            "http.request.method": "GET",
            "http.route": "/v1/items/{item_id}",
            "http.response.status_code": 200,
        }
        serialized = f"{span.name} {dict(span.attributes or {})}"
        assert concrete_id not in serialized
        assert "customer@example.com" not in serialized
        assert "url.path" not in span.attributes
    finally:
        runtime.shutdown()


def test_abuse_metrics_are_strictly_low_cardinality() -> None:
    customer_identifier = "owner@example.com"
    record_abuse_control_decision(
        control=customer_identifier,
        result=customer_identifier,
    )
    payload = render_prometheus().decode("utf-8")

    assert customer_identifier not in payload
    samples = [
        sample
        for family in ABUSE_CONTROL_DECISIONS.collect()
        for sample in family.samples
        if sample.name == "akc_abuse_control_decisions_total"
        and sample.labels == {"control": "other", "result": "other"}
    ]
    assert samples


def test_product_analytics_metrics_are_strictly_low_cardinality() -> None:
    customer_identifier = "owner@example.com"
    record_product_analytics_snapshot(customer_identifier)
    record_product_analytics_event(customer_identifier, result=customer_identifier)
    payload = render_prometheus().decode("utf-8")

    assert customer_identifier not in payload
    snapshot_samples = [
        sample
        for family in PRODUCT_ANALYTICS_SNAPSHOTS.collect()
        for sample in family.samples
        if sample.name == "akc_product_analytics_snapshots_total"
        and sample.labels == {"result": "other"}
    ]
    event_samples = [
        sample
        for family in PRODUCT_ANALYTICS_EVENTS.collect()
        for sample in family.samples
        if sample.name == "akc_product_analytics_events_total"
        and sample.labels == {"event_type": "other", "result": "other"}
    ]
    assert snapshot_samples
    assert event_samples


def test_collection_estimation_and_cost_metrics_have_no_customer_labels() -> None:
    customer_identifier = "owner@example.com"
    observe_collection_estimate_calibration(
        credit_error_ratio=0.10,
        duration_error_ratio=0.20,
        route_mix_error_ratio=0.05,
    )
    observe_collection_retry_ratio(0.01)
    record_collection_gpu_seconds(4.5)
    record_collection_knowledge_tokens(stage=customer_identifier, tokens=120)
    observe_collection_export(
        profile=customer_identifier,
        duration_seconds=3.2,
        storage_amplification_ratio=1.4,
    )
    record_collection_credits_refunded("2.5")

    payload = render_prometheus().decode("utf-8")
    for series in (
        "akc_collection_estimate_credit_error_ratio",
        "akc_collection_estimate_duration_error_ratio",
        "akc_collection_route_mix_error_ratio",
        "akc_collection_retry_ratio",
        "akc_collection_gpu_seconds_total",
        "akc_collection_knowledge_tokens_total",
        "akc_collection_export_duration_seconds",
        "akc_collection_storage_amplification_ratio",
        "akc_collection_credits_refunded_total",
    ):
        assert series in payload
    assert customer_identifier not in payload


def _counter_value(counter: Any, sample_name: str) -> float:
    for family in counter.collect():
        for sample in family.samples:
            if sample.name == sample_name:
                return float(sample.value)
    raise AssertionError(f"missing counter sample {sample_name}")


async def test_transaction_metrics_commit_and_rollback_semantics() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessions = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    committed: list[str] = []
    try:
        async with sessions() as session:
            await session.execute(text("SELECT 1"))
            after_commit_metric(session, committed.append, "committed")
            await session.commit()
        assert committed == ["committed"]

        audit_failures = _counter_value(
            AUDIT_WRITE_FAILURE,
            "akc_audit_write_failure_total",
        )
        async with sessions() as session:
            await session.execute(text("SELECT 1"))
            track_audit_write(session)
            after_commit_metric(session, committed.append, "must-not-run")
            await session.rollback()
            await session.commit()
        assert committed == ["committed"]
        assert (
            _counter_value(
                AUDIT_WRITE_FAILURE,
                "akc_audit_write_failure_total",
            )
            == audit_failures + 1
        )
    finally:
        await engine.dispose()


def test_local_telemetry_is_safe_without_an_exporter() -> None:
    runtime = create_telemetry_runtime(
        enabled=False,
        service_name="akc-api",
        environment="development",
        endpoint=None,
        export_timeout_seconds=5,
    )
    assert runtime.tracer is None
    assert runtime.tracer_provider is None
    runtime.shutdown()


def test_otel_configuration_rejects_credentials_and_is_required_in_production() -> None:
    with pytest.raises(ValueError, match="credential-free origin"):
        Settings(
            env="test",
            otel_enabled=True,
            otel_exporter_otlp_endpoint="https://user:password@collector.example.com",
        )

    with pytest.raises(ValueError, match="production requires OpenTelemetry export"):
        Settings(
            env="production",
            deployment_revision="a" * 40,
            database_url="postgresql+asyncpg://akc:password@db.internal/akc",
            jwt_secret="a" * 48,
            local_background_tasks=False,
            object_store_driver="s3",
            s3_endpoint_url=None,
            s3_use_ambient_credentials=True,
            s3_source_access_key_id="source-access",
            s3_source_secret_access_key="source-secret",
            s3_working_access_key_id="working-access",
            s3_working_secret_access_key="working-secret",
            s3_derived_access_key_id="derived-access",
            s3_derived_secret_access_key="derived-secret",
            s3_audit_access_key_id="audit-access",
            s3_audit_secret_access_key="audit-secret",
            external_ocr_enabled=False,
            private_mode=True,
            clamav_enabled=True,
            allow_development_antivirus_bypass=False,
            metrics_enabled=True,
            otel_enabled=False,
            otel_exporter_otlp_endpoint=None,
            webhook_delivery_enabled=False,
        )
