"""Transaction-scoped tenant context for background workers.

A worker claims a job from a queue that spans every tenant, then does the work
for exactly one of them. The claim is unavoidably cross-tenant; everything after
it is not. This module marks the boundary: once a worker knows whose job it
holds, the rest of the transaction runs with ``app.tenant_id`` set to that
tenant, so the RLS policies that already exist on 106 tables constrain it.

This is currently inert in production: the seven worker roles still hold
``BYPASSRLS``, which is what makes injecting the context safe to ship first.
``docs/audit/V5_WORKER_PRIVILEGE_BOUNDARY.md`` records why removing that
attribute is blocked and what would have to change.

Three rules the callers depend on:

* ``SET LOCAL`` semantics (``set_config(..., is_local => true)``). The setting
  dies with the transaction, so a pooled connection cannot carry one tenant's
  context into the next tenant's work.
* Fail closed. A missing tenant, or a tenant that disagrees with the claimed
  job row, raises. There is no "continue without context" path — that would
  silently widen the worker back to every tenant.
* PostgreSQL only. SQLite is the deterministic test adapter and has no GUCs or
  RLS; asserting context there would be theatre, so the guard reports the
  backend it applied to rather than pretending.

The API surface only sets ``app.tenant_id``. No table in the catalog carries a
``workspace_id`` column, and the project dimension is enforced through
``app.user_id`` in the project-access policies rather than through a GUC of its
own, so there is nothing else honest to set here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

__all__ = [
    "TenantContextError",
    "TenantContextMismatch",
    "TenantContextMissing",
    "WorkerTenantContext",
    "enter_tenant_context",
]

_TENANT_GUC = "app.tenant_id"


class TenantContextError(RuntimeError):
    """A worker transaction could not be bound to exactly one tenant."""


class TenantContextMissing(TenantContextError):
    """No tenant was supplied for work that belongs to one."""


class TenantContextMismatch(TenantContextError):
    """The claimed row's tenant disagrees with the context being set.

    This is the spoofing signal: either the job row moved under the worker or
    the caller passed a tenant that is not the one it is about to act for.
    """


@dataclass(frozen=True, slots=True)
class WorkerTenantContext:
    """What was actually applied, so callers can log or assert on it."""

    backend: str
    tenant_id: uuid.UUID
    applied: bool


def _backend(handle: AsyncSession | AsyncConnection) -> str:
    """Name the dialect for either handle type.

    An ``AsyncSession`` reaches its dialect through ``.bind``; an
    ``AsyncConnection`` carries ``.dialect`` directly. An unbound session has
    neither, and reports as unknown rather than raising — the caller's tenant is
    still validated, and a handle that cannot run SQL cannot leak rows.
    """

    bind = getattr(handle, "bind", None) or handle
    dialect = getattr(bind, "dialect", None)
    return "unknown" if dialect is None else str(dialect.name)


def _coerce(value: object, *, field: str) -> uuid.UUID:
    if value is None:
        raise TenantContextMissing(f"worker_tenant_context_missing:{field}")
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise TenantContextMissing(f"worker_tenant_context_unusable:{field}") from error


async def enter_tenant_context(
    handle: AsyncSession | AsyncConnection,
    *,
    tenant_id: object,
    expected_tenant_id: object = None,
) -> WorkerTenantContext:
    """Bind the current transaction to one tenant, or refuse to proceed.

    ``expected_tenant_id`` is the tenant read off the claimed job row. When it
    is supplied and disagrees with ``tenant_id``, this raises rather than
    picking one — a disagreement means the caller does not know whose work it
    is holding.
    """

    tenant = _coerce(tenant_id, field="tenant_id")
    if expected_tenant_id is not None:
        expected = _coerce(expected_tenant_id, field="expected_tenant_id")
        if expected != tenant:
            raise TenantContextMismatch(
                f"worker_tenant_context_mismatch:{tenant}!={expected}"
            )

    backend = _backend(handle)
    if backend != "postgresql":
        return WorkerTenantContext(backend=backend, tenant_id=tenant, applied=False)

    await handle.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": _TENANT_GUC, "value": str(tenant)},
    )
    return WorkerTenantContext(backend=backend, tenant_id=tenant, applied=True)
