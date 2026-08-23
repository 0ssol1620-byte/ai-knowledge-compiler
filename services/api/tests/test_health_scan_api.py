"""HTTP contract tests for the authenticated Health Scan endpoint.

Each test seeds a real temporary workspace on the local disk and drives the
production app (session cookie, database, RLS) end to end, so the guard
order (401 -> 404 -> 413 -> 200) and the verbatim heuristic-labeled report
are exercised exactly as a desktop client would see them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest_asyncio
from akc_api.main import create_app
from akc_api.settings import Settings

OWNER_EMAIL = "health-scan-owner@example.com"


@pytest_asyncio.fixture
async def api(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'health-scan-api.db').as_posix()}",
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
            yield client, app


@pytest_asyncio.fixture
async def session_client(api: tuple[httpx.AsyncClient, Any]) -> httpx.AsyncClient:
    """A client holding an authenticated session (registered + verified)."""
    client, app = api
    registered = await client.post(
        "/v1/auth/register",
        json={
            "email": OWNER_EMAIL,
            "password": "correct horse battery staple",
            "display_name": "Health Scan Owner",
            "tenant_name": "Health Scan Owner",
        },
    )
    assert registered.status_code == 201, registered.text
    capture = app.state.verification_capture
    message = await capture.take_for(OWNER_EMAIL)
    assert message is not None
    verified = await client.post("/v1/auth/verify-email", json={"token": message.token})
    assert verified.status_code == 200, verified.text
    return client


def _seed_workspace(root: Path) -> None:
    """Duplicate pair + stale markdown link + secret-named file."""
    notes = root / "notes"
    notes.mkdir(parents=True)
    shared = "# Shared heading\n\nidentical body so both files hash alike\n"
    (notes / "alpha.md").write_text(shared, encoding="utf-8")
    (notes / "beta.md").write_text(shared, encoding="utf-8")
    (notes / "index.md").write_text("[missing](gone.md)\n", encoding="utf-8")
    # Benign contents: only the *filename* should trip sensitive_exposure.
    (root / "credentials.txt").write_text("placeholder\n", encoding="utf-8")


async def _scan(client: httpx.AsyncClient, workspace_path: str) -> httpx.Response:
    return await client.post("/v1/health-scan/scan", json={"workspace_path": workspace_path})


async def test_scan_requires_authentication(api: tuple[httpx.AsyncClient, Any]) -> None:
    client, _ = api
    response = await _scan(client, "C:/does/not/matter")
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_scan_reports_duplicates_stale_links_and_sensitive_names(
    session_client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    _seed_workspace(workspace)
    response = await _scan(session_client, str(workspace))
    assert response.status_code == 200, response.text
    report = response.json()

    clusters = report["duplicates"]["exact_duplicate_clusters"]
    duplicated_paths = {path for cluster in clusters for path in cluster["paths"]}
    assert {"notes/alpha.md", "notes/beta.md"} <= duplicated_paths

    stale = report["stale_references"]["stale"]
    assert any(
        entry["file"] == "notes/index.md" and entry["target"] == "gone.md" for entry in stale
    )

    sensitive_rules = {
        finding["rule_id"]: finding["path"]
        for finding in report["sensitive_exposure"]["findings"]
    }
    assert sensitive_rules.get("secret-named-file") == "credentials.txt"

    for section in (
        "sources",
        "duplicates",
        "identity_collisions",
        "conflicting_candidates",
        "stale_references",
        "unresolved_dates",
        "sensitive_exposure",
        "projection_readiness",
        "estimated_compile_work",
    ):
        assert report[section]["label"] == "heuristic", section


async def test_scan_missing_workspace_returns_404(
    session_client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "nope"
    response = await _scan(session_client, str(missing))
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "WORKSPACE_NOT_FOUND"

    also_file = tmp_path / "plain.txt"
    also_file.write_text("not a directory\n", encoding="utf-8")
    file_response = await _scan(session_client, str(also_file))
    assert file_response.status_code == 404, file_response.text


async def test_scan_rejects_workspace_over_file_limit(
    session_client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "bulk-ws"
    bulk = workspace / "bulk"
    bulk.mkdir(parents=True)
    for index in range(5001):
        (bulk / f"f{index:05d}.txt").write_bytes(b"x")
    response = await _scan(session_client, str(workspace))
    assert response.status_code == 413, response.text
    error = response.json()["error"]
    assert error["code"] == "WORKSPACE_TOO_LARGE"
    assert error["details"]["max_workspace_files"] == 5000
