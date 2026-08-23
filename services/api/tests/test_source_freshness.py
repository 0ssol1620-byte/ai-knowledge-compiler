"""Freshness dashboard: SLO math boundaries and the tenant-scoped API surface."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import pytest_asyncio
from akc_api.main import create_app
from akc_api.models import utcnow
from akc_api.settings import Settings
from akc_api.source_freshness import (
    RETRY_BASE_SECONDS,
    RETRY_MAX_SECONDS,
    TIER_SLO_SECONDS,
    FreshnessTier,
    SourceCursor,
    compute_from_cursor,
)
from sqlalchemy import select

_SUPPORT_KEY = "freshness-test-support-key"
_PASSWORD = "correct horse battery staple"  # noqa: S105


def _cursor_row(
    *,
    source_id: str = "git:acme/repo",
    adapter: str = "git",
    updated_at: datetime | None = None,
    cursor: Any = None,
    failure_streak: int = 0,
    tenant_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        source_id=source_id,
        adapter=adapter,
        cursor=cursor if cursor is not None else {},
        updated_at=updated_at if updated_at is not None else utcnow(),
        failure_streak=failure_streak,
        next_retry_at=None,
        tenant_id=tenant_id,
    )


# --- SLO tier boundaries ----------------------------------------------------


@pytest.mark.parametrize(
    ("age_seconds", "expected_tier"),
    [
        (0, FreshnessTier.F0),
        (150, FreshnessTier.F0),
        (300, FreshnessTier.F0),
        (301, FreshnessTier.F1),
        (3_600, FreshnessTier.F1),
        (3_601, FreshnessTier.F2),
        (86_400, FreshnessTier.F2),
        (86_401, FreshnessTier.F3),
        (604_800, FreshnessTier.F3),
    ],
)
def test_unclassified_age_lands_on_the_tightest_covering_tier(
    age_seconds: float, expected_tier: FreshnessTier
) -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    row = _cursor_row(updated_at=now - timedelta(seconds=age_seconds))

    status = compute_from_cursor(row, None, now)

    assert status.freshness_tier is expected_tier
    assert status.slo_target_seconds == expected_tier.slo_seconds


def test_age_beyond_every_slo_breaches_the_weekly_archive_tier() -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    row = _cursor_row(adapter="custom", updated_at=now - timedelta(seconds=604_801))

    status = compute_from_cursor(row, {}, now)

    assert status.freshness_tier is FreshnessTier.F3
    assert status.slo_target_seconds == TIER_SLO_SECONDS[FreshnessTier.F3]
    assert status.breached is True


def test_classified_age_within_slo_never_breaches() -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    for age_seconds, tier in (
        (300, FreshnessTier.F0),
        (3_600, FreshnessTier.F1),
        (86_400, FreshnessTier.F2),
        (604_800, FreshnessTier.F3),
    ):
        row = _cursor_row(updated_at=now - timedelta(seconds=age_seconds))
        status = compute_from_cursor(row, None, now)
        assert status.breached is False, f"age {age_seconds}s breached tier {tier}"


# --- Pinned tiers and breach boundaries --------------------------------------


@pytest.mark.parametrize("pinned", ["F0", FreshnessTier.F0], ids=["string", "enum"])
def test_pinned_tier_holds_even_when_age_would_classify_higher(
    pinned: str | FreshnessTier,
) -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    row = _cursor_row(updated_at=now - timedelta(seconds=120))  # classifies F0 anyway

    status = compute_from_cursor(row, {"freshness_tier": pinned}, now)

    assert status.freshness_tier is FreshnessTier.F0
    assert status.slo_target_seconds == 300


def test_breach_boundary_is_inclusive_of_the_slo_second() -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)

    within = compute_from_cursor(
        _cursor_row(updated_at=now - timedelta(seconds=300)),
        {"freshness_tier": "F0"},
        now,
    )
    breached = compute_from_cursor(
        _cursor_row(updated_at=now - timedelta(seconds=301)),
        {"freshness_tier": "F0"},
        now,
    )

    assert within.breached is False
    assert within.cursor_age_seconds == 300.0
    assert breached.breached is True
    assert breached.slo_target_seconds == 300


def test_explicit_slo_override_replaces_the_tier_default() -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    row = _cursor_row(updated_at=now - timedelta(seconds=45))

    status = compute_from_cursor(row, {"slo_target_seconds": 30}, now)

    assert status.freshness_tier is FreshnessTier.F0  # classified from age
    assert status.slo_target_seconds == 30
    assert status.breached is True


# --- Retry projection ---------------------------------------------------------


def test_healthy_cursor_has_no_projected_retry() -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)

    status = compute_from_cursor(_cursor_row(failure_streak=0), None, now)

    assert status.next_retry_at is None
    assert status.failure_streak == 0


@pytest.mark.parametrize(
    ("streak", "expected_delay"),
    [
        (1, RETRY_BASE_SECONDS),
        (2, RETRY_BASE_SECONDS * 2),
        (3, RETRY_BASE_SECONDS * 2**2),
    ],
)
def test_failure_streak_backs_off_exponentially_from_now(
    streak: int, expected_delay: int
) -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)

    status = compute_from_cursor(_cursor_row(failure_streak=streak), None, now)

    assert status.next_retry_at == now + timedelta(seconds=expected_delay)


def test_backoff_is_capped_at_the_maximum_window() -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)

    status = compute_from_cursor(_cursor_row(failure_streak=24), None, now)

    assert status.next_retry_at == now + timedelta(seconds=RETRY_MAX_SECONDS)


def test_backoff_base_and_cap_are_configurable() -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)

    status = compute_from_cursor(
        _cursor_row(failure_streak=3),
        {"retry_base_seconds": 5, "retry_max_seconds": 15},
        now,
    )

    assert status.next_retry_at == now + timedelta(seconds=15)


# --- Row hygiene ---------------------------------------------------------------


def test_naive_updated_at_reads_as_utc_and_skew_clamps_to_zero() -> None:
    aware_now = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)
    naive_fresh = aware_now.replace(tzinfo=None)  # SQLite round-trips look like this
    future_written = aware_now + timedelta(hours=1)  # clock skew: written "ahead"

    normal = compute_from_cursor(_cursor_row(updated_at=naive_fresh), None, aware_now)
    skewed = compute_from_cursor(_cursor_row(updated_at=future_written), None, aware_now)

    assert normal.last_success_at.tzinfo is UTC
    assert normal.cursor_age_seconds == 0.0
    assert skewed.cursor_age_seconds == 0.0
    assert skewed.breached is False


def test_missing_updated_at_is_a_loud_error() -> None:
    with pytest.raises(ValueError, match="updated_at"):
        compute_from_cursor({"source_id": "git:x", "adapter": "git"}, None, utcnow())


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"head": "abc123"}, "abc123"),
        ({"revision": 7}, "7"),
        ({"head": "", "revision": "fallback"}, "fallback"),
        ({"notes/brief.md": {"sha256": "ff", "mtime_ns": 1}}, None),
        ({}, None),
        ("not-a-mapping", None),
        (None, None),
    ],
)
def test_last_revision_reads_known_identity_keys(payload: Any, expected: str | None) -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)

    status = compute_from_cursor(_cursor_row(cursor=payload), None, now)

    assert status.last_revision == expected


def test_mapping_rows_are_supported_alongside_orm_objects() -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    moment = now - timedelta(seconds=10)
    mapping_row = {
        "source_id": "obsidian:vault",
        "adapter": "obsidian",
        "cursor": {},
        "updated_at": moment,
        "failure_streak": 0,
    }

    from_mapping = compute_from_cursor(mapping_row, None, now)
    from_namespace = compute_from_cursor(
        _cursor_row(source_id="obsidian:vault", adapter="obsidian", updated_at=moment),
        None,
        now,
    )

    assert from_mapping.source_id == "obsidian:vault"
    assert from_mapping == from_namespace


# --- HTTP surface ----------------------------------------------------------------


@pytest_asyncio.fixture
async def freshness_api(tmp_path: Any) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    settings = Settings(
        env="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'freshness.db').as_posix()}",
        data_dir=tmp_path / "data",
        local_background_tasks=False,
        local_analysis_worker_enabled=False,
        clamav_enabled=False,
        allow_development_antivirus_bypass=True,
        test_support_key=_SUPPORT_KEY,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client, app


async def _register_verified_tenant(
    client: httpx.AsyncClient,
    *,
    email: str,
    tenant_name: str,
) -> str:
    registered = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": _PASSWORD,
            "display_name": email.split("@", 1)[0],
            "tenant_name": tenant_name,
        },
    )
    assert registered.status_code == 201, registered.text
    captured = await client.post(
        "/__test__/verification-token",
        headers={"X-AKC-Test-Support-Key": _SUPPORT_KEY},
        json={"email": email},
    )
    assert captured.status_code == 200, captured.text
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": captured.json()["token"]},
    )
    assert verified.status_code == 200, verified.text
    return str(verified.json()["tenant_id"])


async def _seed_cursor(app: Any, **fields: Any) -> None:
    async with app.state.database.sessions() as session:
        session.add(SourceCursor(**fields))
        await session.commit()


async def test_freshness_requires_authentication(
    freshness_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, _ = freshness_api

    response = await client.get("/v1/sources/freshness")

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] in {"AUTH_REQUIRED", "INVALID_SESSION"}


async def test_empty_cursor_table_returns_200_with_no_items(
    freshness_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, _ = freshness_api
    await _register_verified_tenant(
        client, email="empty@example.com", tenant_name="Empty Workspace"
    )

    response = await client.get("/v1/sources/freshness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.0"
    assert payload["items"] == []


async def test_dashboard_lists_only_the_caller_tenants_cursors(
    freshness_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = freshness_api
    tenant_a = await _register_verified_tenant(
        client, email="owner@example.com", tenant_name="Alpha Workspace"
    )
    tenant_b = uuid.uuid4()  # a foreign tenant with its own connector cursors
    fresh_moment = utcnow()

    await _seed_cursor(
        app,
        source_id="git:alpha/repo",
        tenant_id=uuid.UUID(tenant_a),
        adapter="git",
        cursor={"head": "abc123"},
        updated_at=fresh_moment - timedelta(seconds=120),
    )
    await _seed_cursor(
        app,
        source_id="git:beta/foreign-repo",
        tenant_id=tenant_b,
        adapter="git",
        cursor={"head": "secret"},
        updated_at=fresh_moment - timedelta(seconds=30),
    )
    await _seed_cursor(
        app,
        source_id="obsidian:alpha-vault",
        tenant_id=uuid.UUID(tenant_a),
        adapter="obsidian",
        cursor={},
        updated_at=fresh_moment - timedelta(seconds=7_200),
    )
    await _seed_cursor(
        app,
        source_id="git:alpha/flaky",
        tenant_id=uuid.UUID(tenant_a),
        adapter="git",
        cursor={"head": "deadbeef"},
        updated_at=fresh_moment - timedelta(seconds=90),
        failure_streak=3,
    )

    response = await client.get("/v1/sources/freshness")

    assert response.status_code == 200
    items = response.json()["items"]
    by_source = {item["source_id"]: item for item in items}

    assert set(by_source) == {
        "git:alpha/repo",
        "obsidian:alpha-vault",
        "git:alpha/flaky",
    }
    assert "git:beta/foreign-repo" not in by_source
    assert b"secret" not in response.content

    healthy = by_source["git:alpha/repo"]
    assert healthy["adapter"] == "git"
    assert healthy["last_revision"] == "abc123"
    assert healthy["freshness_tier"] == "F2"  # git's default promise
    assert healthy["slo_target_seconds"] == 86_400
    assert healthy["breached"] is False
    assert healthy["next_retry_at"] is None
    assert healthy["failure_streak"] == 0

    stale_vault = by_source["obsidian:alpha-vault"]
    assert stale_vault["freshness_tier"] == "F1"  # obsidian's default promise
    assert stale_vault["slo_target_seconds"] == 3_600
    assert stale_vault["breached"] is True
    assert stale_vault["last_revision"] is None

    flaky = by_source["git:alpha/flaky"]
    assert flaky["failure_streak"] == 3
    assert flaky["next_retry_at"] is not None


async def test_foreign_tenant_rows_do_not_count_in_listing_order(
    freshness_api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, app = freshness_api
    tenant_a = await _register_verified_tenant(
        client, email="solo@example.com", tenant_name="Solo Workspace"
    )
    await _seed_cursor(
        app,
        source_id="git:aaa/first",
        tenant_id=uuid.UUID(tenant_a),
        adapter="git",
        cursor={},
        updated_at=utcnow(),
    )
    for foreign_id in ("git:zzz/intruder", "git:mmm/intruder"):
        await _seed_cursor(
            app,
            source_id=foreign_id,
            tenant_id=uuid.uuid4(),
            adapter="git",
            cursor={},
            updated_at=utcnow(),
        )

    response = await client.get("/v1/sources/freshness")

    assert response.status_code == 200
    assert [item["source_id"] for item in response.json()["items"]] == ["git:aaa/first"]

    async with app.state.database.sessions() as session:
        total = len((await session.scalars(select(SourceCursor))).all())
    assert total == 3  # rows exist; the dashboard simply never sees them


def test_unknown_adapter_without_pin_is_classified_by_age() -> None:
    now = datetime(2026, 8, 23, tzinfo=UTC)
    row = _cursor_row(adapter="webhook", updated_at=now - timedelta(seconds=400))

    status = compute_from_cursor(row, {}, now)

    assert status.freshness_tier is FreshnessTier.F1
    assert status.breached is False
