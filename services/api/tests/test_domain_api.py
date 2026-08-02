from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest_asyncio
from akc_api.main import create_app
from akc_api.settings import Settings

_TEST_SUPPORT_KEY = "domain-api-verification-key-2026"


@pytest_asyncio.fixture
async def domain_api(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        Settings(
            env="test",
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'domain.db').as_posix()}",
            data_dir=tmp_path / "data",
            clamav_enabled=False,
            allow_development_antivirus_bypass=True,
            test_support_key=_TEST_SUPPORT_KEY,
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


async def _register(client: httpx.AsyncClient) -> dict[str, Any]:
    created = await client.post(
        "/v1/auth/register",
        json={
            "email": "domain-owner@example.com",
            "password": "correct horse battery staple",
            "display_name": "Domain Owner",
            "tenant_name": "Domain Workspace",
        },
    )
    assert created.status_code == 201
    captured = await client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": _TEST_SUPPORT_KEY},
        json={"email": "domain-owner@example.com"},
    )
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": captured.json()["token"]},
    )
    assert verified.status_code == 200
    return verified.json()


async def test_domain_pack_discovery_is_authenticated_and_complete(
    domain_api: httpx.AsyncClient,
) -> None:
    assert (await domain_api.get("/v1/domain-packs")).status_code == 401
    await _register(domain_api)

    response = await domain_api.get("/v1/domain-packs")

    assert response.status_code == 200
    assert response.json()["registry_version"] == "1.0.0"
    assert {pack["id"] for pack in response.json()["packs"]} == {
        "study_pack",
        "research_pack",
        "work_project_pack",
        "legal_contract_pack",
        "technical_support_pack",
        "archive_book_pack",
    }
    assert (await domain_api.get("/v1/domain-packs/missing")).status_code == 404


async def test_custom_schema_validation_returns_only_a_content_receipt(
    domain_api: httpx.AsyncClient,
) -> None:
    await _register(domain_api)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"ticket_id": {"type": "string", "maxLength": 80}},
        "required": ["ticket_id"],
    }

    response = await domain_api.post(
        "/v1/schema-profiles/validate",
        json={"schema": schema},
    )

    assert response.status_code == 200
    assert response.json()["schema_sha256"].startswith("sha256:")
    assert "schema" not in response.json()


async def test_custom_schema_cannot_override_provenance(
    domain_api: httpx.AsyncClient,
) -> None:
    await _register(domain_api)

    response = await domain_api.post(
        "/v1/schema-profiles/validate",
        json={
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"evidenceBlockIds": {"type": "array"}},
            }
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CUSTOM_SCHEMA_POLICY_VIOLATION"


async def test_knowledge_blueprints_are_complete_and_plannable(
    domain_api: httpx.AsyncClient,
) -> None:
    await _register(domain_api)

    registry = await domain_api.get("/v1/knowledge-blueprints")
    detail = await domain_api.get("/v1/knowledge-blueprints/corporate-filings")
    plan = await domain_api.post(
        "/v1/knowledge-blueprints/plan",
        json={
            "domain": "finance",
            "object_types": ["company", "filing", "metric"],
            "user_goal": "Compile source-grounded filings",
            "corpus_size": 5000,
            "temporal_structure": "quarterly",
        },
    )

    assert registry.status_code == 200
    assert len(registry.json()["blueprints"]) == 7
    assert set(registry.json()["module_sha256"]) == {
        item["id"] for item in registry.json()["blueprints"]
    }
    assert detail.status_code == 200
    assert len(detail.json()["assets"]) >= 10
    assert plan.status_code == 200
    assert plan.json()["blueprint"] == "corporate-filings"
    assert plan.json()["module_sha256"] == detail.json()["module_sha256"]


async def test_unknown_knowledge_blueprint_fails_closed(
    domain_api: httpx.AsyncClient,
) -> None:
    await _register(domain_api)
    missing = await domain_api.get("/v1/knowledge-blueprints/missing")
    plan = await domain_api.post(
        "/v1/knowledge-blueprints/plan",
        json={
            "domain": "general",
            "object_types": ["document"],
            "user_goal": "Compile",
            "corpus_size": 1,
            "temporal_structure": "none",
            "requested_blueprint": "missing",
        },
    )

    assert missing.status_code == 404
    assert plan.status_code == 422
    assert plan.json()["error"]["code"] == "KNOWLEDGE_BLUEPRINT_NOT_FOUND"
