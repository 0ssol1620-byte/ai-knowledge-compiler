"""HTTP contract tests for POST /v1/ask.

Every test drives the real application (session cookie, database, RLS) the
way a client would. The four contract pillars:

* a fixture world compiles a CURRENT answer that names its claim, evidence
  and world state;
* an absent world -- unconfigured store, empty store, ambiguous store --
  is a 200 UNRESOLVED finding, never an error and never a guess;
* no session is a 401, before any world is touched;
* NOT_AUTHORIZED discloses nothing: no claim ids, no evidence.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest_asyncio
from akc_api.ask_api import (
    SNAPSHOT_SCHEMA_VERSION,
    AskConsumptionRecord,
)
from akc_api.main import create_app
from akc_api.settings import Settings
from akc_cir import publication_manifest
from fastapi import FastAPI

_COMPILER_VERSION = "0.1.0"
_ACTIVE_WS = "ws_20260824_active"
_SUPERSEDED_WS = "ws_20260824_superseded"
_BUILT_AT = "2026-08-24T00:00:00+00:00"

_TEST_SUPPORT_EMAIL = "ask-owner@example.com"


def _claim(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "claim_id": "cl_refund_30d",
        "subject": "refund_window",
        "value": "30 days from delivery",
        "authority": "OFFICIAL",
        "source_status": "ACTIVE",
        "scope": {},
        "extracted_world_state_id": _ACTIVE_WS,
        "evidence_id": "ev_refund_doc_p12",
    }
    base.update(overrides)
    return base


def _snapshot(
    tenant_id: str,
    *,
    world_state_id: str = _ACTIVE_WS,
    status: str = "ACTIVE",
    claims: list[dict[str, Any]] | None = None,
    artifact_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    hashes = (
        artifact_hashes
        if artifact_hashes is not None
        else {"kb.md": "sha256:" + "1" * 64}
    )
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "workspace_id": "personal",
        "world_state_id": world_state_id,
        "status": status,
        "compiler_version": _COMPILER_VERSION,
        "built_at": _BUILT_AT,
        "activated_at": _BUILT_AT,
        "artifact_hashes": hashes,
        "manifest_hash": publication_manifest(
            world_state_id=world_state_id,
            compiler_version=_COMPILER_VERSION,
            artifact_hashes=hashes,
        ).manifest_hash,
        "validation_receipt": {
            "receipt_id": f"rcpt_{world_state_id}",
            "checksums_verified": True,
            "permission_checked": True,
            "integrity_passed": True,
        },
        "claims": [_claim()] if claims is None else claims,
    }


def _write_snapshot(
    store_dir: Path, payload: dict[str, Any], *, partition: str | None = None
) -> Path:
    """Write into the snapshot's own tenant partition unless told otherwise."""
    target = store_dir / (partition if partition is not None else payload["tenant_id"])
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{payload['world_state_id']}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _ensure_store_dir(store_dir: Path) -> Path:
    """Create the (possibly absent) store directory, off the event loop."""
    store_dir.mkdir(parents=True, exist_ok=True)
    return store_dir


class _RecordingSink:
    """A stand-in ReceiptSink capturing what the endpoint hands over."""

    def __init__(self) -> None:
        self.records: list[AskConsumptionRecord] = []

    async def record(self, record: AskConsumptionRecord) -> None:
        self.records.append(record)


@pytest_asyncio.fixture
async def api(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'ask.db').as_posix()}",
        data_dir=tmp_path / "data",
        world_store_dir=tmp_path / "worlds",
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


async def _register_and_verify(
    client: httpx.AsyncClient, app: FastAPI, email: str = _TEST_SUPPORT_EMAIL
) -> str:
    """Register, verify and stay signed in; return the session's tenant id."""
    registered = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "display_name": "Ask Owner",
            "tenant_name": "Ask Workspace",
        },
    )
    assert registered.status_code == 201, registered.text
    capture = app.state.verification_capture
    message = await capture.take_for(email)
    assert message is not None
    verified = await client.post(
        "/v1/auth/verify-email", json={"token": message.token}
    )
    assert verified.status_code == 200, verified.text
    session = await client.get("/v1/auth/session")
    assert session.status_code == 200, session.text
    return str(session.json()["tenant_id"])


async def _ask(client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await client.post("/v1/ask", json={"query": "현재 환불 기간이 얼마인가요?", **body})


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


async def test_unauthenticated_ask_is_rejected_before_any_world_lookup(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, _ = api

    response = await _ask(client)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


# ---------------------------------------------------------------------------
# CURRENT — the fixture world answers and cites itself
# ---------------------------------------------------------------------------


async def test_fixture_world_compiles_current_answer_with_citations(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = api
    store_dir: Path = app.state.settings.world_store_dir
    tenant = await _register_and_verify(client, app)
    _write_snapshot(store_dir, _snapshot(tenant))

    response = await _ask(
        client, query="What is the current refund window for delivered orders?"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "CURRENT"
    assert body["claim_ids"] == ["cl_refund_30d"]
    assert body["world_state_id"] == _ACTIVE_WS
    assert body["evidence"] == [
        {
            "claim_id": "cl_refund_30d",
            "evidence_id": "ev_refund_doc_p12",
            "source_status": "ACTIVE",
        }
    ]
    assert body["intent"] == "current"
    assert body["reason"]


# ---------------------------------------------------------------------------
# UNRESOLVED — every absent-world shape is a finding with a reason
# ---------------------------------------------------------------------------


async def test_unconfigured_world_store_answers_unresolved(
    tmp_path: Path,
) -> None:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'ask-nostore.db').as_posix()}",
        data_dir=tmp_path / "data",
        world_store_dir=None,
        local_background_tasks=False,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            await _register_and_verify(client, app)

            response = await _ask(client)

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "UNRESOLVED"
    assert body["claim_ids"] == []
    assert body["evidence"] == []
    assert body["world_state_id"] == ""
    assert "not configured" in body["reason"]


async def test_store_without_active_world_answers_unresolved(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = api
    await _register_and_verify(client, app)

    # The store directory was never created on disk.
    missing_directory = await _ask(client)
    assert missing_directory.status_code == 200
    assert missing_directory.json()["outcome"] == "UNRESOLVED"
    assert missing_directory.json()["claim_ids"] == []

    # An empty directory reads the same way.
    store_dir: Path = app.state.settings.world_store_dir
    _ensure_store_dir(store_dir)
    empty = await _ask(client)
    assert empty.status_code == 200
    assert empty.json()["outcome"] == "UNRESOLVED"
    assert empty.json()["reason"] == "no ACTIVE world state is published"


async def test_only_non_active_snapshots_answers_unresolved(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = api
    store_dir: Path = app.state.settings.world_store_dir
    tenant = await _register_and_verify(client, app)
    _write_snapshot(
        store_dir,
        _snapshot(tenant, world_state_id=_SUPERSEDED_WS, status="SUPERSEDED"),
    )

    response = await _ask(client)

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "UNRESOLVED"
    assert body["claim_ids"] == []
    assert body["evidence"] == []


async def test_two_active_claims_refuse_instead_of_guessing(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = api
    store_dir: Path = app.state.settings.world_store_dir
    tenant = await _register_and_verify(client, app)
    _write_snapshot(store_dir, _snapshot(tenant))
    _write_snapshot(store_dir, _snapshot(tenant, world_state_id="ws_second_active"))

    response = await _ask(client)

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "UNRESOLVED"
    assert "refusing to guess" in body["reason"]
    assert body["claim_ids"] == []


async def test_tampered_snapshot_fails_closed(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = api
    store_dir: Path = app.state.settings.world_store_dir
    tenant = await _register_and_verify(client, app)
    tampered = _snapshot(tenant)
    tampered["artifact_hashes"]["kb.md"] = "sha256:" + "9" * 64
    _write_snapshot(store_dir, tampered)

    response = await _ask(client)

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "UNRESOLVED"
    assert "unreadable snapshots" in body["reason"]
    assert body["claim_ids"] == []


async def test_pinned_world_must_be_the_active_one(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = api
    store_dir: Path = app.state.settings.world_store_dir
    tenant = await _register_and_verify(client, app)
    _write_snapshot(store_dir, _snapshot(tenant))
    _write_snapshot(
        store_dir,
        _snapshot(
            tenant,
            world_state_id=_SUPERSEDED_WS,
            status="SUPERSEDED",
            claims=[_claim(extracted_world_state_id=_SUPERSEDED_WS)],
        ),
    )

    unknown = await _ask(client, world_state_id="ws_never_written")
    assert unknown.status_code == 200
    assert unknown.json()["outcome"] == "UNRESOLVED"
    assert "was not found" in unknown.json()["reason"]

    stale_pin = await _ask(client, world_state_id=_SUPERSEDED_WS)
    assert stale_pin.status_code == 200
    assert stale_pin.json()["outcome"] == "UNRESOLVED"
    assert "not the ACTIVE world" in stale_pin.json()["reason"]
    assert stale_pin.json()["claim_ids"] == []

    pinned_active = await _ask(client, world_state_id=_ACTIVE_WS)
    assert pinned_active.status_code == 200
    assert pinned_active.json()["outcome"] == "CURRENT"


# ---------------------------------------------------------------------------
# STALE / NOT_AUTHORIZED — what the compiler refuses to serve
# ---------------------------------------------------------------------------


async def test_not_authorized_outcome_discloses_no_claims_or_evidence(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = api
    store_dir: Path = app.state.settings.world_store_dir
    tenant = await _register_and_verify(client, app)
    _write_snapshot(
        store_dir,
        _snapshot(
            tenant,
            claims=[
                _claim(required_permission="board:minuted"),
            ]
        ),
    )

    response = await _ask(client)

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "NOT_AUTHORIZED"
    # §22.1: even the count of withheld candidates is a disclosure.
    assert body["claim_ids"] == []
    assert body["evidence"] == []
    assert body["world_state_id"] == _ACTIVE_WS


async def test_held_permission_serves_the_restricted_claim(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = api
    store_dir: Path = app.state.settings.world_store_dir
    tenant = await _register_and_verify(client, app)
    _write_snapshot(
        store_dir,
        _snapshot(tenant, claims=[_claim(required_permission="owner")]),
    )

    response = await _ask(client)

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "CURRENT"
    assert body["claim_ids"] == ["cl_refund_30d"]


async def test_stale_extraction_is_named_as_the_finding(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = api
    store_dir: Path = app.state.settings.world_store_dir
    tenant = await _register_and_verify(client, app)
    _write_snapshot(
        store_dir,
        _snapshot(
            tenant,
            claims=[_claim(extracted_world_state_id=_SUPERSEDED_WS)],
        ),
    )

    response = await _ask(client)

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "STALE"
    # Stale is a corpus finding: naming which claim went stale *is* the
    # answer record, unlike NOT_AUTHORIZED which must name nothing.
    assert body["claim_ids"] == ["cl_refund_30d"]
    assert body["evidence"][0]["evidence_id"] == "ev_refund_doc_p12"
    assert body["world_state_id"] == _ACTIVE_WS
    assert _SUPERSEDED_WS in body["reason"]


# ---------------------------------------------------------------------------
# Receipt sink seam
# ---------------------------------------------------------------------------


async def test_injected_receipt_sink_receives_the_consumption_record(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = api
    sink = _RecordingSink()
    app.state.receipt_sink = sink
    store_dir: Path = app.state.settings.world_store_dir
    tenant = await _register_and_verify(client, app)
    _write_snapshot(store_dir, _snapshot(tenant))

    asked = await _ask(client)

    assert asked.status_code == 200
    assert len(sink.records) == 1
    record = sink.records[0]
    assert record.outcome == "CURRENT"
    assert record.claim_ids == ("cl_refund_30d",)
    assert record.world_state_id == _ACTIVE_WS
    assert record.intent == "current"
    assert record.query == "현재 환불 기간이 얼마인가요?"
    assert str(record.tenant_id).count("-") == 4  # uuid-shaped tenant identity
    assert isinstance(record.answered_at, datetime)
    assert record.answered_at.tzinfo is UTC


async def test_default_sink_is_noop_and_answer_still_works(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = api
    assert not hasattr(app.state, "receipt_sink")
    store_dir: Path = app.state.settings.world_store_dir
    tenant = await _register_and_verify(client, app)
    _write_snapshot(store_dir, _snapshot(tenant))

    response = await _ask(client)

    assert response.status_code == 200
    assert response.json()["outcome"] == "CURRENT"


# ---------------------------------------------------------------------------
# Tenant isolation — the store partition comes from the session, and every
# snapshot must be bound to the asking tenant
# ---------------------------------------------------------------------------

_OTHER_TENANT_EMAIL = "ask-other-tenant@example.com"


async def _second_tenant_client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_tenant_never_resolves_another_tenants_active_world(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client_a, app = api
    store_dir: Path = app.state.settings.world_store_dir
    tenant_a = await _register_and_verify(client_a, app)
    async with await _second_tenant_client(app) as client_b:
        tenant_b = await _register_and_verify(client_b, app, _OTHER_TENANT_EMAIL)
        assert tenant_a != tenant_b
        # Only tenant B has published anything.
        _write_snapshot(
            store_dir,
            _snapshot(
                tenant_b,
                world_state_id="ws_tenant_b",
                claims=[_claim(claim_id="cl_b", extracted_world_state_id="ws_tenant_b")],
            ),
        )

        unpinned = await _ask(client_a)
        pinned = await _ask(client_a, world_state_id="ws_tenant_b")
        own = await _ask(client_b)

    assert unpinned.status_code == 200
    assert unpinned.json()["outcome"] == "UNRESOLVED"
    assert unpinned.json()["reason"] == "no ACTIVE world state is published"
    assert unpinned.json()["claim_ids"] == []
    assert unpinned.json()["evidence"] == []
    # Pinning another tenant's world is indistinguishable from a world that
    # does not exist: no existence oracle across tenants.
    assert pinned.json()["outcome"] == "UNRESOLVED"
    assert "was not found" in pinned.json()["reason"]
    assert pinned.json()["claim_ids"] == []
    # Positive control: B's world is real and answerable by B.
    assert own.json()["outcome"] == "CURRENT"
    assert own.json()["claim_ids"] == ["cl_b"]


async def test_each_tenant_answers_only_from_its_own_partition(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client_a, app = api
    store_dir: Path = app.state.settings.world_store_dir
    tenant_a = await _register_and_verify(client_a, app)
    async with await _second_tenant_client(app) as client_b:
        tenant_b = await _register_and_verify(client_b, app, _OTHER_TENANT_EMAIL)
        # Both ACTIVE: one shared directory would refuse as ambiguous or
        # serve the wrong tenant; partitions make each lookup unambiguous.
        _write_snapshot(
            store_dir,
            _snapshot(tenant_a, claims=[_claim(claim_id="cl_a")]),
        )
        _write_snapshot(
            store_dir,
            _snapshot(
                tenant_b,
                world_state_id="ws_tenant_b",
                claims=[_claim(claim_id="cl_b", extracted_world_state_id="ws_tenant_b")],
            ),
        )

        answer_a = await _ask(client_a)
        answer_b = await _ask(client_b)

    assert answer_a.json()["claim_ids"] == ["cl_a"]
    assert answer_a.json()["world_state_id"] == _ACTIVE_WS
    assert answer_b.json()["claim_ids"] == ["cl_b"]
    assert answer_b.json()["world_state_id"] == "ws_tenant_b"


async def test_snapshot_bound_to_another_tenant_fails_closed_without_fallback(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = api
    store_dir: Path = app.state.settings.world_store_dir
    tenant = await _register_and_verify(client, app)
    foreign_tenant = "00000000-0000-4000-8000-0000000000bb"
    # The caller's own valid ACTIVE world sits beside a foreign-bound file
    # placed (or symlinked) into the caller's partition. Skipping the foreign
    # file would serve the own world; the lookup must refuse instead.
    _write_snapshot(store_dir, _snapshot(tenant))
    _write_snapshot(
        store_dir,
        _snapshot(foreign_tenant, world_state_id="ws_foreign", status="SUPERSEDED"),
        partition=tenant,
    )

    response = await _ask(client)
    pinned = await _ask(client, world_state_id="ws_foreign")

    for answered in (response, pinned):
        body = answered.json()
        assert body["outcome"] == "UNRESOLVED"
        assert "bound to a different tenant" in body["reason"]
        assert foreign_tenant not in body["reason"]
        assert body["claim_ids"] == []
        assert body["evidence"] == []
        assert body["world_state_id"] == ""


async def test_snapshot_without_tenant_binding_fails_closed_without_fallback(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = api
    store_dir: Path = app.state.settings.world_store_dir
    tenant = await _register_and_verify(client, app)
    _write_snapshot(store_dir, _snapshot(tenant))
    unbound = _snapshot(tenant, world_state_id="ws_unbound", status="SUPERSEDED")
    del unbound["tenant_id"]
    _write_snapshot(store_dir, unbound, partition=tenant)

    response = await _ask(client)

    body = response.json()
    assert body["outcome"] == "UNRESOLVED"
    assert "unreadable snapshots" in body["reason"]
    assert "ws_unbound.json" in body["reason"]
    # The perfectly valid ACTIVE world beside it is not served either.
    assert body["claim_ids"] == []
    assert body["world_state_id"] == ""


async def test_unpartitioned_snapshot_at_store_root_refuses_every_lookup(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = api
    store_dir: Path = app.state.settings.world_store_dir
    tenant = await _register_and_verify(client, app)
    _write_snapshot(store_dir, _snapshot(tenant))
    legacy = _snapshot(tenant, world_state_id="ws_legacy_flat")
    (store_dir / "ws_legacy_flat.json").write_text(json.dumps(legacy), encoding="utf-8")

    response = await _ask(client)

    body = response.json()
    assert body["outcome"] == "UNRESOLVED"
    assert "unpartitioned snapshots" in body["reason"]
    assert body["claim_ids"] == []


async def test_previous_schema_version_is_unreadable(
    api: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, app = api
    store_dir: Path = app.state.settings.world_store_dir
    tenant = await _register_and_verify(client, app)
    old = _snapshot(tenant)
    old["schema_version"] = SNAPSHOT_SCHEMA_VERSION - 1
    del old["tenant_id"]
    _write_snapshot(store_dir, old, partition=tenant)

    response = await _ask(client)

    body = response.json()
    assert body["outcome"] == "UNRESOLVED"
    assert "unsupported snapshot schema version" in body["reason"]
    assert body["claim_ids"] == []
