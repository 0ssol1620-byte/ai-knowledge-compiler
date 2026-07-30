from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import pytest_asyncio
from akc_api.main import create_app
from akc_api.malware import MalwareDetectedError
from akc_api.models import (
    AuditEvent,
    Document,
    DocumentVersion,
    SourceFile,
    UploadSession,
)
from akc_api.settings import Settings
from akc_url_fetcher.fetcher import FetchResult, UrlFetchError
from akc_url_fetcher.models import UrlFetchTask
from akc_url_fetcher.security import UrlSecretCodec
from akc_url_fetcher.worker import UrlFetchRuntime, UrlFetchWorker
from sqlalchemy import func, select

_TEST_SUPPORT_KEY = "url-ingestion-verification-key-2026"


@pytest_asyncio.fixture
async def url_api(
    tmp_path: Path,
) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'url-api.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=True,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
        test_support_key=_TEST_SUPPORT_KEY,
        url_ingestion_enabled=True,
        url_fetch_max_attempts=2,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            await _register(client)
            project = await client.post("/v1/projects", json={"name": "URL evidence"})
            assert project.status_code == 201, project.text
            app.state.url_test_project_id = project.json()["id"]
            yield client, app


async def _register(client: httpx.AsyncClient) -> None:
    registered = await client.post(
        "/v1/auth/register",
        json={
            "email": "url-owner@example.com",
            "password": "correct horse battery staple",
            "display_name": "URL Owner",
            "tenant_name": "URL Workspace",
        },
    )
    assert registered.status_code == 201, registered.text
    captured = await client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": _TEST_SUPPORT_KEY},
        json={"email": "url-owner@example.com"},
    )
    assert captured.status_code == 200, captured.text
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": captured.json()["token"]},
    )
    assert verified.status_code == 200, verified.text


async def _enqueue(
    client: httpx.AsyncClient,
    app: Any,
    *,
    title: str,
    url: str,
    key: str | None = None,
) -> httpx.Response:
    headers = {"Idempotency-Key": key} if key else None
    return await client.post(
        "/v1/documents",
        headers=headers,
        json={
            "project_id": app.state.url_test_project_id,
            "title": title,
            "source_url": url,
        },
    )


def test_url_secret_codec_encrypts_full_url_and_keys_query() -> None:
    codec = UrlSecretCodec(
        encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        query_hmac_secret=b"query-secret-must-be-at-least-32-bytes",
    )
    protected = codec.protect(
        "https://Example.COM/reports/%72eport.pdf?token=customer-secret"
    )

    assert protected.canonical_url == "https://example.com/reports/%72eport.pdf"
    assert "customer-secret" not in protected.canonical_url
    assert b"customer-secret" not in protected.ciphertext
    assert protected.query_hmac
    assert protected.query_hmac != hashlib.sha256(
        b"token=customer-secret"
    ).hexdigest()
    assert (
        codec.reveal(protected.ciphertext)
        == "https://example.com/reports/%72eport.pdf?token=customer-secret"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/report.pdf",
        "https://user:password@example.com/report.pdf",
        "https://example.com:8443/report.pdf",
        "https://example.com/report.pdf#fragment",
    ],
)
def test_url_secret_codec_rejects_unsafe_forms_before_storage(url: str) -> None:
    codec = UrlSecretCodec(
        encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        query_hmac_secret=b"query-secret-must-be-at-least-32-bytes",
    )
    with pytest.raises(UrlFetchError):
        codec.protect(url)


async def test_api_enqueues_202_replays_exactly_and_never_exposes_query(
    url_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = url_api
    source_url = "https://example.com/report.pdf?token=top-secret"
    first = await _enqueue(
        client,
        app,
        title="Confidential URL",
        url=source_url,
        key="url-create-001",
    )
    replay = await _enqueue(
        client,
        app,
        title="Confidential URL",
        url=source_url,
        key="url-create-001",
    )

    assert first.status_code == 202, first.text
    assert replay.status_code == 202
    assert replay.content == first.content
    payload = first.json()
    assert payload["canonical_url"] == "https://example.com/report.pdf"
    assert payload["query_hmac"]
    assert "top-secret" not in first.text
    assert payload["status_url"] == f"/v1/url-fetch-tasks/{payload['task_id']}"

    status = await client.get(payload["status_url"])
    assert status.status_code == 200
    assert "top-secret" not in status.text
    assert status.json()["status"] == "queued"

    task_id = uuid.UUID(payload["task_id"])
    async with app.state.database.sessions() as session:
        task = await session.get(UrlFetchTask, task_id)
        task_count = await session.scalar(select(func.count(UrlFetchTask.id)))
        audits = list(
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "document.url_fetch_queued"
                )
            )
        )
    assert task is not None
    assert task_count == 1
    assert b"top-secret" not in task.encrypted_url
    assert app.state.url_secret_codec.reveal(task.encrypted_url) == source_url
    assert len(audits) == 1
    assert "top-secret" not in json.dumps(audits[0].metadata_json)

    cancelled = await client.post(f"{payload['status_url']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert "top-secret" not in cancelled.text


async def test_feature_flag_remains_fail_closed(
    url_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = url_api
    app.state.settings.url_ingestion_enabled = False
    response = await _enqueue(
        client,
        app,
        title="Disabled",
        url="https://example.com/disabled.txt",
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "URL_INGESTION_DISABLED"


async def test_document_tombstone_cancels_url_task_before_purge(
    url_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = url_api
    accepted = await _enqueue(
        client,
        app,
        title="Delete before fetch",
        url="https://example.com/delete.txt?secret=redacted",
    )
    payload = accepted.json()
    app.state.settings.local_background_tasks = False
    deleted = await client.delete(f"/v1/documents/{payload['document_id']}")
    assert deleted.status_code == 202, deleted.text

    async with app.state.database.sessions() as session:
        task = await session.get(UrlFetchTask, uuid.UUID(payload["task_id"]))
        document = await session.get(Document, uuid.UUID(payload["document_id"]))
    assert task is not None
    assert task.status == "cancelled"
    assert task.last_error_code == "URL_FETCH_TARGET_DELETED"
    assert task.lease_token is None
    assert task.cancelled_at is not None
    assert document is not None
    assert document.deletion_requested_at is not None


async def test_worker_quarantines_scans_promotes_and_persists_exactly_once(
    url_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = url_api
    accepted = await _enqueue(
        client,
        app,
        title="Fetched PDF",
        url="https://example.com/fetched.pdf?signature=private",
    )
    assert accepted.status_code == 202, accepted.text
    task_id = uuid.UUID(accepted.json()["task_id"])
    body = b"%PDF-1.7\nURL ingestion evidence\n%%EOF"
    fetch_calls: list[str] = []
    scanned: list[bytes] = []

    class FakeFetcher:
        def fetch(self, url: str) -> FetchResult:
            fetch_calls.append(url)
            return FetchResult(
                body=body,
                content_type="application/pdf",
                sha256=hashlib.sha256(body).hexdigest(),
                canonical_url="https://example.com/fetched.pdf",
                query_sha256=None,
                retrieved_at=datetime(2026, 7, 29, tzinfo=UTC),
                redirect_count=0,
                final_ip="93.184.216.34",
            )

    async def scanner(stream: Any) -> Any:
        scanned.append(stream.read())
        stream.seek(0)
        return SimpleNamespace(status="clean")

    worker = UrlFetchWorker(
        engine=app.state.database.engine,
        store=app.state.object_store,
        codec=app.state.url_secret_codec,
        scanner=scanner,
        runtime=UrlFetchRuntime(
            environment="test",
            lease_seconds=60,
            max_attempts=2,
            backoff_base_seconds=1,
            backoff_max_seconds=2,
            backoff_jitter_ratio=0,
            poll_seconds=0.01,
            max_bytes=1024 * 1024,
        ),
        fetcher=FakeFetcher(),
    )
    competing_worker = UrlFetchWorker(
        engine=app.state.database.engine,
        store=app.state.object_store,
        codec=app.state.url_secret_codec,
        scanner=scanner,
        runtime=UrlFetchRuntime(
            environment="test",
            lease_seconds=60,
            max_attempts=2,
            backoff_base_seconds=1,
            backoff_max_seconds=2,
            backoff_jitter_ratio=0,
            poll_seconds=0.01,
            max_bytes=1024 * 1024,
        ),
        fetcher=FakeFetcher(),
    )
    results = await asyncio.gather(
        worker.run_once(task_id=task_id),
        competing_worker.run_once(task_id=task_id),
    )
    assert sorted(results) == [False, True]
    assert await worker.run_once(task_id=task_id) is False
    assert fetch_calls == ["https://example.com/fetched.pdf?signature=private"]
    assert scanned == [body]

    async with app.state.database.sessions() as session:
        task = await session.get(UrlFetchTask, task_id)
        document = await session.get(Document, task.document_id if task else uuid.uuid4())
        sources = list(await session.scalars(select(SourceFile)))
        uploads = list(await session.scalars(select(UploadSession)))
        versions = list(await session.scalars(select(DocumentVersion)))
    assert task is not None
    assert task.status == "completed"
    assert task.source_sha256 == hashlib.sha256(body).hexdigest()
    assert task.source_file_id is not None
    assert document is not None
    assert document.status == "SECURITY_VERIFIED"
    assert document.source_file_id == task.source_file_id
    assert len(sources) == len(uploads) == len(versions) == 1
    assert await app.state.object_store.read_source(sources[0].storage_key) == body
    assert "private" not in json.dumps(
        {
            "canonical_url": task.canonical_url,
            "query_hmac": task.query_hmac,
        }
    )


async def test_retryable_fetch_exhausts_into_dlq_without_source(
    url_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = url_api
    accepted = await _enqueue(
        client,
        app,
        title="Unavailable",
        url="https://example.com/retry.txt?credential=never-log",
    )
    task_id = uuid.UUID(accepted.json()["task_id"])

    class FailingFetcher:
        def fetch(self, _url: str) -> FetchResult:
            raise UrlFetchError("URL_FETCH_NETWORK_ERROR", retryable=True)

    async def scanner(_stream: Any) -> Any:
        pytest.fail("scanner must not run when fetch failed")

    worker = UrlFetchWorker(
        engine=app.state.database.engine,
        store=app.state.object_store,
        codec=app.state.url_secret_codec,
        scanner=scanner,
        runtime=UrlFetchRuntime(
            environment="test",
            lease_seconds=60,
            max_attempts=2,
            backoff_base_seconds=0.1,
            backoff_max_seconds=0.1,
            backoff_jitter_ratio=0,
            poll_seconds=0.01,
            max_bytes=1024 * 1024,
        ),
        fetcher=FailingFetcher(),
    )
    assert await worker.run_once(task_id=task_id) is True
    async with app.state.database.sessions.begin() as session:
        task = await session.get(UrlFetchTask, task_id)
        assert task is not None
        assert task.status == "retry"
        task.available_at = datetime.now(UTC)
    assert await worker.run_once(task_id=task_id) is True

    async with app.state.database.sessions() as session:
        task = await session.get(UrlFetchTask, task_id)
        source_count = await session.scalar(select(func.count(SourceFile.id)))
        audits = list(
            await session.scalars(
                select(AuditEvent).where(AuditEvent.target_id == str(task.document_id))
            )
        )
    assert task is not None
    assert task.status == "dead_letter"
    assert task.attempt_count == 2
    assert task.last_error_code == "URL_FETCH_NETWORK_ERROR"
    assert source_count == 0
    assert "never-log" not in json.dumps([row.metadata_json for row in audits])


async def test_inflight_cancellation_fences_persistence_and_cleans_source(
    url_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = url_api
    accepted = await _enqueue(
        client,
        app,
        title="Cancelled race",
        url="https://example.com/race.txt?secret=redacted",
    )
    payload = accepted.json()
    task_id = uuid.UUID(payload["task_id"])
    body = b"lease fenced body"
    fetch_started = threading.Event()
    release_fetch = threading.Event()

    class BlockingFetcher:
        def fetch(self, _url: str) -> FetchResult:
            fetch_started.set()
            assert release_fetch.wait(timeout=5)
            return FetchResult(
                body=body,
                content_type="text/plain",
                sha256=hashlib.sha256(body).hexdigest(),
                canonical_url="https://example.com/race.txt",
                query_sha256=None,
                retrieved_at=datetime(2026, 7, 29, tzinfo=UTC),
                redirect_count=0,
                final_ip="93.184.216.34",
            )

    async def scanner(stream: Any) -> Any:
        assert stream.read() == body
        stream.seek(0)
        return SimpleNamespace(status="clean")

    worker = UrlFetchWorker(
        engine=app.state.database.engine,
        store=app.state.object_store,
        codec=app.state.url_secret_codec,
        scanner=scanner,
        runtime=UrlFetchRuntime(
            environment="test",
            lease_seconds=60,
            max_attempts=2,
            backoff_base_seconds=1,
            backoff_max_seconds=2,
            backoff_jitter_ratio=0,
            poll_seconds=0.01,
            max_bytes=1024 * 1024,
        ),
        fetcher=BlockingFetcher(),
    )
    running = asyncio.create_task(worker.run_once(task_id=task_id))
    assert await asyncio.to_thread(fetch_started.wait, 5)
    cancelled = await client.post(f"/v1/url-fetch-tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    release_fetch.set()
    assert await running is True

    async with app.state.database.sessions() as session:
        task = await session.get(UrlFetchTask, task_id)
        source_count = await session.scalar(select(func.count(SourceFile.id)))
    assert task is not None
    assert task.status == "cancelled"
    assert source_count == 0
    source_key = (
        f"tenants/{task.tenant_id}/projects/{task.project_id}/"
        f"sources/url/{task.id}/{hashlib.sha256(body).hexdigest()}.txt"
    )
    with pytest.raises(FileNotFoundError):
        await app.state.object_store.read_source(source_key)


async def test_malware_result_fails_closed_without_promotion(
    url_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = url_api
    accepted = await _enqueue(
        client,
        app,
        title="Malware",
        url="https://example.com/malware.txt",
    )
    task_id = uuid.UUID(accepted.json()["task_id"])
    body = b"malicious but MIME-valid text"

    class FakeFetcher:
        def fetch(self, _url: str) -> FetchResult:
            return FetchResult(
                body=body,
                content_type="text/plain",
                sha256=hashlib.sha256(body).hexdigest(),
                canonical_url="https://example.com/malware.txt",
                query_sha256=None,
                retrieved_at=datetime(2026, 7, 29, tzinfo=UTC),
                redirect_count=0,
                final_ip="93.184.216.34",
            )

    async def scanner(_stream: Any) -> Any:
        raise MalwareDetectedError("test-signature")

    worker = UrlFetchWorker(
        engine=app.state.database.engine,
        store=app.state.object_store,
        codec=app.state.url_secret_codec,
        scanner=scanner,
        runtime=UrlFetchRuntime(
            environment="test",
            lease_seconds=60,
            max_attempts=2,
            backoff_base_seconds=1,
            backoff_max_seconds=2,
            backoff_jitter_ratio=0,
            poll_seconds=0.01,
            max_bytes=1024 * 1024,
        ),
        fetcher=FakeFetcher(),
    )
    assert await worker.run_once(task_id=task_id) is True
    async with app.state.database.sessions() as session:
        task = await session.get(UrlFetchTask, task_id)
        source_count = await session.scalar(select(func.count(SourceFile.id)))
    assert task is not None
    assert task.status == "failed"
    assert task.last_error_code == "URL_FETCH_MALWARE_DETECTED"
    assert source_count == 0
