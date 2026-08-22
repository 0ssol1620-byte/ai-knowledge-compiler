from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from akc_api.main import create_app
from akc_api.settings import Settings


@pytest_asyncio.fixture
async def health_client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        Settings(
            env="test",
            deployment_revision="a" * 40,
            database_url=(f"sqlite+aiosqlite:///{(tmp_path / 'health.db').as_posix()}"),
            data_dir=tmp_path / "data",
            local_background_tasks=False,
            clamav_enabled=False,
            allow_development_antivirus_bypass=True,
        )
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://testserver",
        ) as client,
    ):
        yield client


@pytest.mark.asyncio
async def test_health_endpoints_expose_the_configured_revision(
    health_client: httpx.AsyncClient,
) -> None:
    live = await health_client.get("/health/live")
    ready = await health_client.get("/health/ready")

    assert live.status_code == ready.status_code == 200
    assert live.json() == {"status": "ok", "revision": "a" * 40}
    assert ready.json() == {"status": "ready", "revision": "a" * 40}


def test_production_requires_an_immutable_deployment_revision() -> None:
    with pytest.raises(
        ValueError,
        match="production requires an immutable deployment revision",
    ):
        Settings(env="production")
