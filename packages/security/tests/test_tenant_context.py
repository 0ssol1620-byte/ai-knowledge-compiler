"""Failure paths of the worker tenant-context guard.

The success path is asserted end to end by the PostgreSQL gate
(``infra/postgres/schema_security_gate.py``); what matters here is that the
guard refuses rather than degrades, because a guard that returns quietly when it
cannot bind a tenant leaves the worker scoped to every tenant.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from akc_security.tenant_context import (
    TenantContextMismatch,
    TenantContextMissing,
    enter_tenant_context,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


class _Dialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeHandle:
    """Records what would run, so the PostgreSQL branch is observable.

    Shaped like ``AsyncConnection`` — ``.dialect`` directly, no ``.bind``.
    """

    def __init__(self, name: str = "postgresql", observed: str | None = None) -> None:
        self.dialect = _Dialect(name)
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self._observed = observed

    async def execute(self, statement: Any, parameters: dict[str, Any]) -> None:
        self.statements.append((str(statement), parameters))

    async def scalar(self, statement: Any, parameters: dict[str, Any]) -> str | None:
        self.statements.append((str(statement), parameters))
        return self._observed


async def test_sets_transaction_local_guc_on_postgresql() -> None:
    handle = _FakeHandle()
    tenant = uuid.uuid4()

    applied = await enter_tenant_context(handle, tenant_id=tenant)

    assert applied.applied is True
    assert applied.tenant_id == tenant
    statement, parameters = handle.statements[0]
    # `true` is the is_local argument: the setting must die with the
    # transaction, or a pooled connection carries it into the next tenant.
    assert "set_config" in statement
    assert "true" in statement
    assert parameters == {"name": "app.tenant_id", "value": str(tenant)}


async def test_missing_tenant_raises_rather_than_skipping() -> None:
    handle = _FakeHandle()
    with pytest.raises(TenantContextMissing):
        await enter_tenant_context(handle, tenant_id=None)
    assert handle.statements == []


async def test_unusable_tenant_raises() -> None:
    handle = _FakeHandle()
    with pytest.raises(TenantContextMissing):
        await enter_tenant_context(handle, tenant_id="not-a-uuid")
    assert handle.statements == []


async def test_job_row_tenant_disagreement_raises() -> None:
    handle = _FakeHandle()
    with pytest.raises(TenantContextMismatch):
        await enter_tenant_context(
            handle,
            tenant_id=uuid.uuid4(),
            expected_tenant_id=uuid.uuid4(),
        )
    # Nothing is set when the caller does not know whose work it holds.
    assert handle.statements == []


async def test_matching_expected_tenant_is_accepted() -> None:
    handle = _FakeHandle()
    tenant = uuid.uuid4()
    applied = await enter_tenant_context(
        handle, tenant_id=tenant, expected_tenant_id=str(tenant)
    )
    assert applied.applied is True


async def test_sqlite_is_reported_not_pretended() -> None:
    """SQLite has no GUCs; the guard must say so rather than claim success."""

    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with AsyncSession(bind=engine) as session:
            await session.execute(text("SELECT 1"))
            applied = await enter_tenant_context(session, tenant_id=uuid.uuid4())
    finally:
        await engine.dispose()
    assert applied.backend == "sqlite"
    assert applied.applied is False
