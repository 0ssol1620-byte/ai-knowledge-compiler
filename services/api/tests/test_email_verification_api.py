"""End-to-end evidence for verified-email activation and free-tier controls."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from akc_api.main import create_app
from akc_api.models import (
    AuditEvent,
    CreditLedger,
    EmailVerificationDelivery,
    EmailVerificationToken,
    FreeDailyUsage,
    ProcessingJob,
    User,
)
from akc_api.settings import Settings
from cryptography.fernet import Fernet
from sqlalchemy import func, select

_SUPPORT_KEY = "email-verification-api-support-key"


@pytest_asyncio.fixture
async def verification_api(
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    settings = Settings(
        env="test",
        database_url=(f"sqlite+aiosqlite:///{(tmp_path / 'verification.db').as_posix()}"),
        data_dir=tmp_path / "data",
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
        test_support_key=_SUPPORT_KEY,
        register_client_limit=100,
        register_account_limit=100,
        register_captcha_after=100,
        resend_client_limit=100,
        resend_account_limit=100,
        resend_captcha_after=100,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client, app


async def _register_pending(
    client: httpx.AsyncClient,
    *,
    email: str,
) -> dict[str, Any]:
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "display_name": "Verification Owner",
            "tenant_name": f"Verification {uuid.uuid4()}",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["email_verified"] is False
    return response.json()


async def _take_token(client: httpx.AsyncClient, email: str) -> str:
    response = await client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": _SUPPORT_KEY},
        json={"email": email},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["token"])


async def _verify(client: httpx.AsyncClient, email: str) -> dict[str, Any]:
    token = await _take_token(client, email)
    response = await client.post(
        "/v1/auth/verify-email",
        json={"token": token},
    )
    assert response.status_code == 200, response.text
    assert response.json()["email_verified"] is True
    return {**response.json(), "token": token}


async def test_activation_gates_processing_and_grants_credit_exactly_once(
    verification_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = verification_api
    email = "activation@example.test"
    registration = await _register_pending(client, email=email)
    blocked = await client.post(
        "/v1/uploads/initiate",
        json={
            "filename": "blocked.txt",
            "size": 1,
            "content_type": "text/plain",
            "sha256": hashlib.sha256(b"x").hexdigest(),
        },
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "EMAIL_VERIFICATION_REQUIRED"

    async with app.state.database.sessions() as session:
        grants_before = await session.scalar(
            select(func.count(CreditLedger.id)).where(
                CreditLedger.tenant_id == uuid.UUID(registration["tenant_id"]),
                CreditLedger.entry_type == "grant",
            )
        )
        user = await session.get(User, uuid.UUID(registration["user_id"]))
    assert grants_before == 0
    assert user is not None and user.email_verified_at is None

    verified = await _verify(client, email)
    replay = await client.post(
        "/v1/auth/verify-email",
        json={"token": verified["token"]},
    )
    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "INVALID_OR_EXPIRED_VERIFICATION_TOKEN"

    async with app.state.database.sessions() as session:
        grants = list(
            await session.scalars(
                select(CreditLedger).where(
                    CreditLedger.tenant_id == uuid.UUID(registration["tenant_id"]),
                    CreditLedger.entry_type == "grant",
                )
            )
        )
        token_row = await session.scalar(select(EmailVerificationToken))
        delivery = await session.scalar(select(EmailVerificationDelivery))
    assert len(grants) == 1
    assert grants[0].credits == Decimal("50")
    assert grants[0].operation_key == "bootstrap:verified-free-credit"
    assert token_row is not None
    assert token_row.token_hash != verified["token"]
    assert delivery is not None
    assert verified["token"].encode() not in delivery.encrypted_payload


async def test_resend_is_enumeration_safe_and_invalidates_prior_token(
    verification_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, _ = verification_api
    email = "resend@example.test"
    await _register_pending(client, email=email)
    original = await _take_token(client, email)

    missing = await client.post(
        "/v1/auth/resend-verification",
        json={"email": "missing@example.test"},
    )
    pending = await client.post(
        "/v1/auth/resend-verification",
        json={"email": email},
    )
    assert missing.status_code == pending.status_code == 202
    assert missing.json() == pending.json() == {"status": "accepted"}

    old_result = await client.post(
        "/v1/auth/verify-email",
        json={"token": original},
    )
    assert old_result.status_code == 400
    fresh = await _take_token(client, email)
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": fresh},
    )
    assert verified.status_code == 200


async def test_test_support_route_is_bounded_hidden_and_single_consumer(
    verification_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, _ = verification_api
    email = "support-route@example.test"
    await _register_pending(client, email=email)
    wrong = await client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": "wrong"},
        json={"email": email},
    )
    assert wrong.status_code == 404
    assert "/__test__/verification-token" not in (await client.get("/openapi.json")).json()["paths"]
    await _take_token(client, email)
    consumed = await client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": _SUPPORT_KEY},
        json={"email": email},
    )
    assert consumed.status_code == 404

    with pytest.raises(ValueError, match="permitted only in test"):
        Settings(env="development", test_support_key=_SUPPORT_KEY)


async def test_verify_rate_limit_returns_retry_after(tmp_path: Path) -> None:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'rate.db').as_posix()}",
        data_dir=tmp_path / "rate-data",
        verify_client_limit=1,
        verify_window_seconds=60,
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://testserver",
        ) as client,
    ):
        first = await client.post(
            "/v1/auth/verify-email",
            json={"token": "x" * 64},
        )
        second = await client.post(
            "/v1/auth/verify-email",
            json={"token": "x" * 64},
        )
    assert first.status_code == 400
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "60"
    assert second.json()["error"]["details"]["retry_after_seconds"] == 60


async def test_daily_file_cap_is_transactional(tmp_path: Path) -> None:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'files.db').as_posix()}",
        data_dir=tmp_path / "file-data",
        test_support_key=_SUPPORT_KEY,
        free_daily_file_cap=1,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://testserver",
        ) as client:
            email = "file-cap@example.test"
            registration = await _register_pending(client, email=email)
            await _verify(client, email)
            first = await client.post(
                "/v1/uploads/initiate",
                headers={"Idempotency-Key": "file-cap-first"},
                json={
                    "filename": "first.txt",
                    "size": 1,
                    "content_type": "text/plain",
                    "sha256": hashlib.sha256(b"a").hexdigest(),
                },
            )
            second = await client.post(
                "/v1/uploads/initiate",
                headers={"Idempotency-Key": "file-cap-second"},
                json={
                    "filename": "second.txt",
                    "size": 1,
                    "content_type": "text/plain",
                    "sha256": hashlib.sha256(b"b").hexdigest(),
                },
            )
        async with app.state.database.sessions() as session:
            usage = await session.scalar(
                select(FreeDailyUsage).where(
                    FreeDailyUsage.tenant_id == uuid.UUID(registration["tenant_id"])
                )
            )
            denial_audit = await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == uuid.UUID(registration["tenant_id"]),
                    AuditEvent.action == "abuse.free_daily_cap_denied",
                )
            )
    assert first.status_code == 201
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) > 0
    assert usage is not None and usage.file_count == 1
    assert denial_audit is not None


async def test_duplicate_hash_is_blocked_tenant_wide_before_second_upload(
    tmp_path: Path,
) -> None:
    settings = Settings(
        env="test",
        database_url=(f"sqlite+aiosqlite:///{(tmp_path / 'duplicate.db').as_posix()}"),
        data_dir=tmp_path / "duplicate-data",
        test_support_key=_SUPPORT_KEY,
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://testserver",
        ) as client,
    ):
        email = "duplicate@example.test"
        registration = await _register_pending(client, email=email)
        await _verify(client, email)
        content = b"one free processing claim"
        digest = hashlib.sha256(content).hexdigest()
        first = await client.post(
            "/v1/uploads/initiate",
            headers={"Idempotency-Key": "duplicate-first"},
            json={
                "filename": "first.txt",
                "size": len(content),
                "content_type": "text/plain",
                "sha256": digest,
            },
        )
        assert first.status_code == 201, first.text
        upload = first.json()
        assert (
            await client.put(
                upload["upload_url"],
                content=content,
                headers=upload["headers"],
            )
        ).status_code == 204
        assert (
            await client.post(
                f"/v1/uploads/{upload['upload_id']}/complete",
                headers={"Idempotency-Key": "duplicate-first-complete"},
                json={"sha256": digest},
            )
        ).status_code == 200
        duplicate = await client.post(
            "/v1/uploads/initiate",
            headers={"Idempotency-Key": "duplicate-second"},
            json={
                "filename": "second.txt",
                "size": len(content),
                "content_type": "text/plain",
                "sha256": digest,
            },
        )
        async with app.state.database.sessions() as session:
            denial = await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == uuid.UUID(registration["tenant_id"]),
                    AuditEvent.action == "abuse.duplicate_source_denied",
                )
            )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "FREE_DUPLICATE_SOURCE"
    assert denial is not None


def test_production_public_registration_requires_real_controls() -> None:
    common: dict[str, Any] = {
        "env": "production",
        "deployment_revision": "a" * 40,
        "jwt_secret": "j" * 40,
        "database_url": "postgresql+asyncpg://akc@database/akc",
        "local_background_tasks": False,
        "object_store_driver": "s3",
        "s3_endpoint_url": "https://objects.example.test",
        "s3_source_access_key_id": "source-access",
        "s3_source_secret_access_key": "source-secret",
        "s3_working_access_key_id": "working-access",
        "s3_working_secret_access_key": "working-secret",
        "s3_derived_access_key_id": "derived-access",
        "s3_derived_secret_access_key": "derived-secret",
        "s3_audit_access_key_id": "audit-access",
        "s3_audit_secret_access_key": "audit-secret",
        "clamav_enabled": True,
        "allow_development_antivirus_bypass": False,
        "metrics_enabled": True,
        "otel_enabled": True,
        "otel_exporter_otlp_endpoint": "https://otel.example.test",
        "redis_url": "rediss://redis.example.test:6380/0",
        "abuse_identity_hmac_secret": "a" * 40,
        "verification_hmac_secret": "v" * 40,
        "pdf_password_hmac_secret": "p" * 40,
        "pdf_password_encryption_key": Fernet.generate_key().decode(),
        "verification_delivery_encryption_key": Fernet.generate_key().decode(),
        "idempotency_response_encryption_key": Fernet.generate_key().decode(),
        "email_verification_provider": "disabled",
        "captcha_provider": "disabled",
    }
    with pytest.raises(
        ValueError,
        match="public production registration requires verified email delivery",
    ):
        Settings(**common)

    with pytest.raises(ValueError, match="forbids development email capture"):
        Settings(
            **{
                **common,
                "allow_public_registration": False,
                "email_verification_provider": "capture",
            }
        )


async def test_failed_gpu_cap_creates_no_job(tmp_path: Path) -> None:
    """The GPU-cost reservation and job creation share one transaction."""

    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'gpu.db').as_posix()}",
        data_dir=tmp_path / "gpu-data",
        test_support_key=_SUPPORT_KEY,
        local_background_tasks=True,
        local_analysis_worker_enabled=True,
        free_daily_gpu_cost_usd_cap=Decimal("0.010000"),
        free_gpu_cost_per_visual_page_usd=Decimal("0.020000"),
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://testserver",
        ) as client:
            email = "gpu-cap@example.test"
            await _register_pending(client, email=email)
            verified = await _verify(client, email)
            project = await client.post("/v1/projects", json={"name": "GPU cap"})
            content = b"one native page"
            digest = hashlib.sha256(content).hexdigest()
            initiated = await client.post(
                "/v1/uploads/initiate",
                json={
                    "project_id": project.json()["id"],
                    "filename": "gpu.txt",
                    "size": len(content),
                    "content_type": "text/plain",
                    "sha256": digest,
                },
            )
            upload = initiated.json()
            assert (
                await client.put(
                    upload["upload_url"],
                    content=content,
                    headers=upload["headers"],
                )
            ).status_code == 204
            assert (
                await client.post(
                    f"/v1/uploads/{upload['upload_id']}/complete",
                    json={"sha256": digest},
                )
            ).status_code == 200
            assert (
                await client.post(f"/v1/documents/{upload['document_id']}/analyze")
            ).status_code == 202
            async with app.state.database.sessions() as session:
                from akc_api.models import Page

                page = await session.scalar(
                    select(Page).where(Page.tenant_id == uuid.UUID(verified["tenant_id"]))
                )
                assert page is not None
                page.route = "visual"
                await session.commit()
            rejected = await client.post(
                f"/v1/documents/{upload['document_id']}/compile",
                headers={"Idempotency-Key": "gpu-cap-compile"},
                json={"external_processing_consent": False},
            )
        async with app.state.database.sessions() as session:
            jobs = await session.scalar(select(func.count(ProcessingJob.id)))
    assert rejected.status_code == 429
    assert rejected.json()["error"]["details"]["dimension"] == "gpu_cost_usd"
    assert jobs == 0


async def test_worker_enforces_daily_page_cap_before_persisting_pages(
    tmp_path: Path,
) -> None:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'pages.db').as_posix()}",
        data_dir=tmp_path / "page-data",
        test_support_key=_SUPPORT_KEY,
        local_background_tasks=True,
        local_analysis_worker_enabled=True,
        free_daily_file_cap=3,
        free_daily_page_cap=1,
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://testserver",
        ) as client,
    ):
        email = "page-cap@example.test"
        registration = await _register_pending(client, email=email)
        await _verify(client, email)
        project = await client.post("/v1/projects", json={"name": "Page cap"})
        assert project.status_code == 201

        async def upload_and_analyze(content: bytes, filename: str) -> dict[str, Any]:
            digest = hashlib.sha256(content).hexdigest()
            initiated = await client.post(
                "/v1/uploads/initiate",
                json={
                    "project_id": project.json()["id"],
                    "filename": filename,
                    "size": len(content),
                    "content_type": "text/plain",
                    "sha256": digest,
                },
            )
            assert initiated.status_code == 201, initiated.text
            upload = initiated.json()
            assert (
                await client.put(
                    upload["upload_url"],
                    content=content,
                    headers=upload["headers"],
                )
            ).status_code == 204
            assert (
                await client.post(
                    f"/v1/uploads/{upload['upload_id']}/complete",
                    json={"sha256": digest},
                )
            ).status_code == 200
            queued = await client.post(f"/v1/documents/{upload['document_id']}/analyze")
            assert queued.status_code == 202, queued.text
            return (await client.get(f"/v1/documents/{upload['document_id']}/analysis")).json()

        first = await upload_and_analyze(b"first page", "first.txt")
        second = await upload_and_analyze(b"second page", "second.txt")
        async with app.state.database.sessions() as session:
            usage = await session.scalar(
                select(FreeDailyUsage).where(
                    FreeDailyUsage.tenant_id == uuid.UUID(registration["tenant_id"])
                )
            )
    assert first["status"] == "completed"
    assert first["page_count"] == 1
    assert second["status"] == "dead_letter"
    assert second["error_code"] == "FREE_DAILY_PAGE_CAP"
    assert second["page_count"] == 0
    assert usage is not None and usage.page_count == 1
