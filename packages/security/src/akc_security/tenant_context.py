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

``enter_tenant_context`` sets ``app.tenant_id`` and nothing else. No table in
the catalog carries a ``workspace_id`` column, and the project dimension is
enforced through ``app.user_id`` in the project-access policies rather than
through a GUC of its own.

Two further boundaries live here, added for the worker-authorization work and
documented in ``docs/audit/V5_CONTROL_PLANE_BOUNDARY.md``:

* ``enter_control_plane_context`` declares that a transaction is doing
  cross-tenant control-plane work — queue discovery, scheduling, claiming,
  leasing or retention — and names which. A queue has no tenant until a row is
  read, so that transaction cannot be tenant-scoped; declaring the purpose is
  what makes the exemption narrow, auditable and refusable.
* ``enter_claim_context`` binds a transaction to one *claim*: the job, tenant,
  project, lease token and lease expiry that the worker actually holds. It
  refuses on any disagreement, so a worker cannot reach a tenant it did not
  claim, reuse another job's lease, or act on a lease that has run out.

The two are mutually exclusive by construction. Binding a tenant clears the
control-plane declaration, so a transaction that discovered work across tenants
loses that reach the moment it starts doing the work.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

__all__ = [
    "CONTROL_PLANE_PURPOSES",
    "ControlPlaneContext",
    "ControlPlanePurposeRejected",
    "TenantContextError",
    "TenantContextMismatch",
    "TenantContextMissing",
    "WorkerClaim",
    "WorkerClaimContext",
    "WorkerClaimOwnerMismatch",
    "WorkerLeaseExpired",
    "WorkerTenantContext",
    "enter_claim_context",
    "enter_control_plane_context",
    "enter_tenant_context",
]

_TENANT_GUC = "app.tenant_id"
_PROJECT_GUC = "app.project_id"
_CLAIM_GUC = "app.claim_id"
_LEASE_GUC = "app.lease_token"
_CONTROL_PLANE_GUC = "app.control_plane"

#: The only reasons a transaction may read across tenants. The database repeats
#: this list in the control-plane policies, so a purpose that is not one of
#: these does not merely fail an assertion here — it returns no rows there.
CONTROL_PLANE_PURPOSES = frozenset(
    {"job_discovery", "scheduling", "claim", "lease", "retention"}
)


class TenantContextError(RuntimeError):
    """A worker transaction could not be bound to exactly one tenant."""


class TenantContextMissing(TenantContextError):
    """No tenant was supplied for work that belongs to one."""


class TenantContextMismatch(TenantContextError):
    """The claimed row's tenant disagrees with the context being set.

    This is the spoofing signal: either the job row moved under the worker or
    the caller passed a tenant that is not the one it is about to act for.
    """


class WorkerLeaseExpired(TenantContextError):
    """The lease the worker holds had already run out.

    A worker whose lease expired has been superseded — another worker may hold
    the job now. Continuing would produce two writers for one job.
    """


class WorkerClaimOwnerMismatch(TenantContextError):
    """The claim row is owned by a different worker.

    Distinct from an expired lease: the lease is live, it just is not this
    worker's. Reusing it is the compromised-worker case the binding exists for.
    """


class ControlPlanePurposeRejected(TenantContextError):
    """A cross-tenant transaction named no purpose, or one that is not allowed.

    Also raised when a tenant is already bound: a transaction doing one
    tenant's work does not get to reopen the cross-tenant view.
    """


@dataclass(frozen=True, slots=True)
class WorkerTenantContext:
    """What was actually applied, so callers can log or assert on it."""

    backend: str
    tenant_id: uuid.UUID
    applied: bool


@dataclass(frozen=True, slots=True)
class WorkerClaim:
    """One claimed unit of work, as read off the claim row.

    ``claim_id`` is the primary key of the row carrying the lease — the task,
    invocation or request the worker holds — because that is what the database
    policies compare against. ``claimed_by`` is the worker identity recorded on
    the claim, not the identity of the process asking.
    """

    claim_id: uuid.UUID
    tenant_id: uuid.UUID
    project_id: uuid.UUID | None
    lease_token: uuid.UUID
    lease_expires_at: datetime
    claimed_by: str


@dataclass(frozen=True, slots=True)
class WorkerClaimContext:
    """What the claim binding applied."""

    backend: str
    claim: WorkerClaim
    applied: bool


@dataclass(frozen=True, slots=True)
class ControlPlaneContext:
    """The declared cross-tenant purpose, for logs and assertions."""

    backend: str
    purpose: str
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
    # Binding a tenant ends any cross-tenant reach the same transaction was
    # granted for discovery. The control-plane policies also require the tenant
    # GUC to be unset, so this is the second of two locks rather than the only
    # one — but it is the one that does not depend on the policy being right.
    await handle.execute(
        text("SELECT set_config(:name, '', true)"),
        {"name": _CONTROL_PLANE_GUC},
    )
    return WorkerTenantContext(backend=backend, tenant_id=tenant, applied=True)


async def enter_control_plane_context(
    handle: AsyncSession | AsyncConnection,
    *,
    purpose: str,
) -> ControlPlaneContext:
    """Declare that this transaction reads control-plane metadata across tenants.

    A queue poll has no tenant until a row is read, so the claim step cannot be
    tenant-scoped. What it can be is *named*: the transaction says which of the
    five allowed purposes it is serving, the control-plane policies compare the
    declaration against the same list, and anything else sees nothing.

    Refuses when a tenant is already bound. That direction matters — a
    transaction already doing one tenant's work must not be able to reopen the
    cross-tenant view partway through.
    """

    if purpose not in CONTROL_PLANE_PURPOSES:
        raise ControlPlanePurposeRejected(f"control_plane_purpose_rejected:{purpose}")

    backend = _backend(handle)
    if backend != "postgresql":
        return ControlPlaneContext(backend=backend, purpose=purpose, applied=False)

    bound = await handle.scalar(
        text("SELECT NULLIF(current_setting(:name, true), '')"),
        {"name": _TENANT_GUC},
    )
    if bound:
        raise ControlPlanePurposeRejected(f"control_plane_tenant_already_bound:{bound}")

    await handle.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": _CONTROL_PLANE_GUC, "value": purpose},
    )
    return ControlPlaneContext(backend=backend, purpose=purpose, applied=True)


def _coerce_optional(value: object, *, field: str) -> uuid.UUID | None:
    return None if value is None else _coerce(value, field=field)


def _require_match(
    supplied: object,
    held: uuid.UUID | None,
    *,
    field: str,
) -> None:
    """Compare what the caller was told against what the claim row says.

    ``None`` on the caller's side means "not asserted" and is skipped. ``None``
    on the claim's side with an assertion present is a mismatch, not a pass —
    that is the forged-project case.
    """

    if supplied is None:
        return
    expected = _coerce(supplied, field=field)
    if held is None or held != expected:
        raise TenantContextMismatch(f"worker_claim_mismatch:{field}:{held}!={expected}")


async def enter_claim_context(
    handle: AsyncSession | AsyncConnection,
    *,
    claim: WorkerClaim,
    worker_id: str,
    now: datetime,
    expected_tenant_id: object = None,
    expected_project_id: object = None,
    expected_claim_id: object = None,
    expected_lease_token: object = None,
) -> WorkerClaimContext:
    """Bind the transaction to one claim, or refuse.

    Everything the database policies compare against is set here and nowhere
    else: tenant, project, claim row and lease token. Five things have to agree
    before any of them is set —

    * every identifier on the claim is present and well formed;
    * ``claimed_by`` is this worker, not another one holding a live lease;
    * the lease has not expired as of ``now``;
    * each ``expected_*`` the caller was told matches what the claim row says;
    * the handle speaks a dialect where any of this means anything.

    Nothing is written on failure. A partially applied binding is worse than
    none: it would leave a tenant set with no claim, which the policies read as
    ordinary tenant-scoped access.
    """

    if not worker_id:
        raise TenantContextMissing("worker_claim_context_missing:worker_id")
    tenant = _coerce(claim.tenant_id, field="tenant_id")
    claim_id = _coerce(claim.claim_id, field="claim_id")
    lease_token = _coerce(claim.lease_token, field="lease_token")
    project_id = _coerce_optional(claim.project_id, field="project_id")

    if not claim.claimed_by:
        raise TenantContextMissing("worker_claim_context_missing:claimed_by")
    if claim.claimed_by != worker_id:
        raise WorkerClaimOwnerMismatch(
            f"worker_claim_owner_mismatch:{claim.claimed_by}!={worker_id}"
        )

    expires_at = claim.lease_expires_at
    if expires_at is None:
        raise TenantContextMissing("worker_claim_context_missing:lease_expires_at")
    if expires_at.tzinfo is None or now.tzinfo is None:
        # A naive timestamp compared against an aware one raises inside the
        # comparison; refusing here names the defect instead.
        raise TenantContextMissing("worker_claim_context_unusable:lease_expires_at")
    if expires_at <= now:
        raise WorkerLeaseExpired(f"worker_lease_expired:{claim_id}@{expires_at}")

    _require_match(expected_tenant_id, tenant, field="tenant_id")
    _require_match(expected_claim_id, claim_id, field="claim_id")
    _require_match(expected_lease_token, lease_token, field="lease_token")
    _require_match(expected_project_id, project_id, field="project_id")

    normalised = WorkerClaim(
        claim_id=claim_id,
        tenant_id=tenant,
        project_id=project_id,
        lease_token=lease_token,
        lease_expires_at=expires_at,
        claimed_by=claim.claimed_by,
    )

    backend = _backend(handle)
    if backend != "postgresql":
        return WorkerClaimContext(backend=backend, claim=normalised, applied=False)

    for name, value in (
        (_TENANT_GUC, str(tenant)),
        (_PROJECT_GUC, "" if project_id is None else str(project_id)),
        (_CLAIM_GUC, str(claim_id)),
        (_LEASE_GUC, str(lease_token)),
        (_CONTROL_PLANE_GUC, ""),
    ):
        await handle.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": name, "value": value},
        )
    return WorkerClaimContext(backend=backend, claim=normalised, applied=True)
