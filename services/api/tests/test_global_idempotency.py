"""Global tenant mutation idempotency contract evidence."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from akc_api.main import create_app, router
from akc_api.models import ApiKey, IdempotencyRecord, Project, utcnow
from akc_api.settings import Settings
from fastapi.routing import APIRoute
from sqlalchemy import func, select


@pytest_asyncio.fixture
async def idempotency_api(
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    settings = Settings(
        env="test",
        database_url=(f"sqlite+aiosqlite:///{(tmp_path / 'idempotency.db').as_posix()}"),
        data_dir=tmp_path / "data",
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            registered = await client.post(
                "/v1/auth/register",
                json={
                    "email": "idempotency-owner@example.com",
                    "password": "correct horse battery staple",
                    "display_name": "Idempotency Owner",
                    "tenant_name": "Idempotency Workspace",
                },
            )
            assert registered.status_code == 201
            capture = app.state.verification_capture
            assert capture is not None
            message = await capture.take_for("idempotency-owner@example.com")
            assert message is not None
            verified = await client.post(
                "/v1/auth/verify-email",
                json={"token": message.token},
            )
            assert verified.status_code == 200
            yield client, app


async def test_concurrent_project_create_replays_exact_winner_and_conflicts(
    idempotency_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = idempotency_api
    headers = {"Idempotency-Key": "concurrent-project-create"}
    replica = create_app(app.state.settings.model_copy(deep=True))
    async with replica.router.lifespan_context(replica):
        replica_transport = httpx.ASGITransport(
            app=replica,
            raise_app_exceptions=True,
        )
        async with httpx.AsyncClient(
            transport=replica_transport,
            base_url="http://testserver",
            cookies=client.cookies,
        ) as replica_client:
            first, second = await asyncio.gather(
                client.post(
                    "/v1/projects",
                    headers=headers,
                    json={"name": "One"},
                ),
                replica_client.post(
                    "/v1/projects",
                    headers=headers,
                    json={"name": "One"},
                ),
            )

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    conflict = await client.post(
        "/v1/projects",
        headers=headers,
        json={"name": "Different"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    async with app.state.database.sessions() as session:
        projects = int(
            await session.scalar(select(func.count(Project.id)).where(Project.name == "One")) or 0
        )
        records = list(
            await session.scalars(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.endpoint == "POST:/v1/projects",
                    IdempotencyRecord.idempotency_key == "concurrent-project-create",
                )
            )
        )
    assert projects == 1
    assert len(records) == 1
    assert records[0].state == "completed"
    assert records[0].response_status == 201
    assert records[0].response_body is None
    assert records[0].response_body_ciphertext
    assert records[0].expires_at >= records[0].created_at + timedelta(days=29)


async def test_secret_response_replays_without_plaintext_storage(
    idempotency_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = idempotency_api
    headers = {"Idempotency-Key": "api-key-secret-replay"}
    payload = {"name": "automation", "scopes": ["api:read"]}

    first = await client.post("/v1/api-keys", headers=headers, json=payload)
    replay = await client.post("/v1/api-keys", headers=headers, json=payload)
    assert first.status_code == replay.status_code == 201
    assert replay.json() == first.json()
    assert first.json()["key"].startswith("akc_live_")

    async with app.state.database.sessions() as session:
        api_key_count = int(await session.scalar(select(func.count(ApiKey.id))) or 0)
        record = await session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.endpoint == "POST:/v1/api-keys",
                IdempotencyRecord.idempotency_key == "api-key-secret-replay",
            )
        )
    assert api_key_count == 1
    assert record is not None
    assert record.response_body is None
    assert record.response_body_ciphertext is not None
    assert first.json()["key"].encode() not in record.response_body_ciphertext


async def test_crash_rolls_back_mutation_and_record_then_retry_succeeds(
    idempotency_api: tuple[httpx.AsyncClient, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app = idempotency_api
    import akc_api.main as main_module

    original_audit = main_module.audit
    calls = 0

    async def fail_once(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic pre-commit crash")
        return await original_audit(*args, **kwargs)

    monkeypatch.setattr(main_module, "audit", fail_once)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies=client.cookies,
    ) as crash_client:
        failed = await crash_client.post(
            "/v1/projects",
            headers={"Idempotency-Key": "crash-safe-project"},
            json={"name": "Crash safe"},
        )
        assert failed.status_code == 500
        retry = await crash_client.post(
            "/v1/projects",
            headers={"Idempotency-Key": "crash-safe-project"},
            json={"name": "Crash safe"},
        )

    assert retry.status_code == 201, retry.text
    async with app.state.database.sessions() as session:
        project_count = int(
            await session.scalar(select(func.count(Project.id)).where(Project.name == "Crash safe"))
            or 0
        )
        records = list(
            await session.scalars(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.idempotency_key == "crash-safe-project"
                )
            )
        )
    assert project_count == 1
    assert len(records) == 1
    assert records[0].state == "completed"


async def test_incomplete_record_conflicts_until_expiry_then_is_replaced(
    idempotency_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = idempotency_api
    headers = {"Idempotency-Key": "expiring-project"}
    payload = {"name": "Expiring"}
    first = await client.post("/v1/projects", headers=headers, json=payload)
    assert first.status_code == 201

    async with app.state.database.sessions.begin() as session:
        record = await session.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == "expiring-project")
        )
        assert record is not None
        record.state = "started"
        record.response_status = None
        record.response_body_ciphertext = None

    incomplete = await client.post("/v1/projects", headers=headers, json=payload)
    assert incomplete.status_code == 409
    assert incomplete.json()["error"]["code"] == "IDEMPOTENCY_INCOMPLETE"

    async with app.state.database.sessions.begin() as session:
        record = await session.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == "expiring-project")
        )
        assert record is not None
        record.expires_at = utcnow() - timedelta(seconds=1)

    replacement = await client.post("/v1/projects", headers=headers, json=payload)
    assert replacement.status_code == 201
    assert replacement.json()["id"] != first.json()["id"]


async def test_terminal_error_response_is_replayed_exactly(
    idempotency_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, _ = idempotency_api
    headers = {"Idempotency-Key": "privacy-policy-conflict"}
    payload = {"external_transfer_allowed": True}

    first = await client.patch("/v1/settings", headers=headers, json=payload)
    replay = await client.patch("/v1/settings", headers=headers, json=payload)

    assert first.status_code == replay.status_code == 409
    assert first.json() == replay.json()
    assert first.json()["error"]["code"] == "PRIVATE_MODE_EXTERNAL_TRANSFER_DENIED"


async def test_key_validation_enforces_printable_200_character_contract(
    idempotency_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, _ = idempotency_api
    for key in ("contains space", "x" * 201):
        rejected = await client.post(
            "/v1/projects",
            headers={"Idempotency-Key": key},
            json={"name": "Rejected key"},
        )
        assert rejected.status_code == 400
        assert rejected.json()["error"]["code"] == "IDEMPOTENCY_KEY_INVALID"

    accepted = await client.post(
        "/v1/projects",
        headers={"Idempotency-Key": "x" * 200},
        json={"name": "Maximum key"},
    )
    assert accepted.status_code == 201


def test_all_required_mutation_routes_publish_idempotency_contract() -> None:
    expected = {
        ("POST", "/v1/api-keys"),
        ("DELETE", "/v1/api-keys/{key_id}"),
        ("POST", "/v1/projects"),
        ("PATCH", "/v1/projects/{project_id}"),
        ("POST", "/v1/uploads/initiate"),
        ("POST", "/v1/upload-sessions"),
        ("POST", "/v1/uploads/{upload_id}/parts/sign"),
        ("POST", "/v1/uploads/{upload_id}/complete"),
        ("POST", "/v1/upload-sessions/{upload_id}/finalize"),
        ("POST", "/v1/uploads/{upload_id}/abort"),
        ("POST", "/v1/upload-sessions/{upload_id}/abort"),
        ("POST", "/v1/documents"),
        ("POST", "/v1/documents/{document_id}/analyze"),
        ("POST", "/v1/documents/{document_id}/compile"),
        ("POST", "/v1/pages/{page_id}/retry"),
        ("POST", "/v1/pages/{page_id}/reprocess"),
        ("PATCH", "/v1/blocks/{block_id}"),
        ("POST", "/v1/review-items/{review_id}/resolve"),
        ("POST", "/v1/projects/{project_id}/exports"),
        ("POST", "/v1/jobs/{job_id}/exports"),
        ("PATCH", "/v1/settings"),
        ("PATCH", "/v1/privacy"),
        ("DELETE", "/v1/documents/{document_id}"),
        ("DELETE", "/v1/projects/{project_id}"),
        ("POST", "/v1/webhooks"),
        ("PATCH", "/v1/webhooks/{webhook_id}"),
        ("DELETE", "/v1/webhooks/{webhook_id}"),
        (
            "POST",
            "/v1/webhooks/{webhook_id}/deliveries/{delivery_id}/replay",
        ),
        ("POST", "/v1/admin/dispatch-dlq/{event_id}/replay"),
        ("POST", "/v1/admin/jobs/{job_id}/retry"),
    }
    routes = {
        (method, route.path): route
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    for identity in expected:
        route = routes[identity]
        assert getattr(route.endpoint, "__akc_idempotent__", False)
        header_parameters = {
            parameter.alias.casefold() for parameter in route.dependant.header_params
        }
        assert "idempotency-key" in header_parameters
