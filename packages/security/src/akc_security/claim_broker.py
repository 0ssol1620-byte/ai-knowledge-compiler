"""Client for the queue claim brokers, and the starvation detector beside it.

``0035_claim_broker`` moved the cross-tenant queue read out of the workers and
into one ``SECURITY DEFINER`` function per queue, owned by a role that can do
nothing else. A worker no longer reads the queue; it asks for a claim and is
told five identifiers.

Two things live here because they are two halves of the same problem.

**The client** enforces the return surface at run time. Founder decision F-1
fixed it at claim id, tenant, project, lease token and lease expiry, and said
plainly that returning more is a design violation. A review catches that once; a
check catches it every time somebody edits the function.

**The detector** answers the question the design creates. With the broker in
place a worker that cannot see its queue gets *no error* — it gets no rows, which
looks exactly like an idle queue. That is the arming failure mode: silent, and
the one most likely to happen. Telling the two apart needs a backlog number from
something other than the worker's own read path, which is what the
``…_depth`` probe beside each broker is for.

Neither half is used in production yet. The workers' existing claim paths still
run, and ``0035`` is inert while the worker roles hold ``BYPASSRLS``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from akc_security.tenant_context import (
    TenantContextError,
    TenantContextMissing,
    WorkerCallback,
    WorkerClaim,
    enter_control_plane_context,
)

__all__ = [
    "BROKER_RETURN_COLUMNS",
    "CALLBACK_RESOLVER_RETURN_COLUMNS",
    "ClaimBrokerContractViolation",
    "ClaimHealth",
    "ClaimObservation",
    "ClaimStarvationDetector",
    "claim_backlog",
    "claim_via_broker",
    "resolve_callback_target",
]

#: The exact result surface. Fixed by founder decision F-1 (2026-08-11) and
#: repeated in ``infra/postgres/control_plane_registry.py`` and in the migration.
BROKER_RETURN_COLUMNS: Final = (
    "claim_id",
    "tenant_id",
    "project_id",
    "lease_token",
    "lease_expires_at",
)

#: The callback resolver's surface. Three identifiers, no lease: a callback has
#: none, and a resolver that returned one would be minting the thing the claim
#: binding exists to compare against.
CALLBACK_RESOLVER_RETURN_COLUMNS: Final = (
    "callback_id",
    "tenant_id",
    "project_id",
)

# A function name is interpolated into SQL — an identifier cannot be bound as a
# parameter. So it is not taken from the caller as free text: it must match the
# shape the migration emits, and nothing else is executed.
_BROKER_NAME_PREFIX = "akc_claim_"
_RESOLVER_NAME_PREFIX = "akc_resolve_"
_BROKER_NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


class ClaimBrokerContractViolation(TenantContextError):
    """The broker returned something other than the five agreed identifiers.

    Raised rather than filtered. A broker that grew a column has either been
    edited or replaced, and both are worth stopping for.
    """


class ClaimHealth(StrEnum):
    """What an empty poll meant.

    Four situations produce an empty poll and only one is an incident:
    ``IDLE`` (nothing pending), ``BLOCKED`` (pending, but every row is leased to
    somebody else, so waiting is correct), ``CONTENDED`` (claimable work exists
    and this worker lost a race), and ``STARVED`` (claimable work exists and this
    worker keeps getting nothing — row-level security is hiding it).

    From inside the worker all four look the same: no rows and no error. The
    whole point of the enum is that they are never the same value.
    """

    HEALTHY = "healthy"
    IDLE = "idle"
    BLOCKED = "blocked"
    CONTENDED = "contended"
    STARVED = "starved"


@dataclass(frozen=True, slots=True)
class ClaimObservation:
    """One poll, classified."""

    health: ClaimHealth
    backlog_depth: int
    claimable_depth: int
    consecutive_zero_polls: int

    @property
    def alert(self) -> bool:
        """Only starvation pages anyone. An idle queue is not an incident."""

        return self.health is ClaimHealth.STARVED


def _validate_function(function: str, *, prefix: str = _BROKER_NAME_PREFIX) -> str:
    if not function.startswith(prefix):
        raise TenantContextMissing(f"claim_broker_name_rejected:{function}")
    if not function or set(function) - _BROKER_NAME_CHARS:
        raise TenantContextMissing(f"claim_broker_name_rejected:{function}")
    return function


def _coerce_optional(value: object) -> uuid.UUID | None:
    if value is None:
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def claim_via_broker(
    handle: AsyncSession | AsyncConnection,
    *,
    function: str,
    worker_id: str,
    lease_seconds: int,
    purpose: str = "claim",
) -> WorkerClaim | None:
    """Ask a queue's broker for one claim, or learn there is nothing to do.

    Returns ``None`` when the queue has nothing claimable — which is also what
    an armed worker with no visibility gets, so a caller that only looks at the
    return value cannot tell the two apart. That is what
    :class:`ClaimStarvationDetector` is for.

    ``claimed_by`` on the returned claim is this worker: the broker granted the
    lease to this caller and to nobody else, so the caller is the owner by
    construction rather than by comparison.
    """

    _validate_function(function)
    if not worker_id:
        raise TenantContextMissing("claim_broker_missing:worker_id")
    if lease_seconds <= 0:
        raise TenantContextMissing(f"claim_broker_lease_invalid:{lease_seconds}")

    await enter_control_plane_context(handle, purpose=purpose)
    result = await handle.execute(
        text(f"SELECT * FROM {function}(:lease_seconds)"),  # noqa: S608 - validated identifier
        {"lease_seconds": lease_seconds},
    )
    row = result.mappings().first()
    if row is None:
        return None
    if tuple(row.keys()) != BROKER_RETURN_COLUMNS:
        raise ClaimBrokerContractViolation(
            f"claim_broker_surface_changed:{function}:{','.join(row.keys())}"
        )
    return WorkerClaim(
        claim_id=uuid.UUID(str(row["claim_id"])),
        tenant_id=uuid.UUID(str(row["tenant_id"])),
        project_id=_coerce_optional(row["project_id"]),
        lease_token=uuid.UUID(str(row["lease_token"])),
        lease_expires_at=_as_datetime(row["lease_expires_at"]),
        claimed_by=worker_id,
    )


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    raise ClaimBrokerContractViolation(f"claim_broker_lease_expiry_unusable:{value!r}")


async def resolve_callback_target(
    handle: AsyncSession | AsyncConnection,
    *,
    function: str,
    invocation_id: uuid.UUID,
    purpose: str = "job_discovery",
) -> WorkerCallback | None:
    """Ask which tenant a callback's row belongs to, or learn it is not one.

    A provider callback names a row and nothing else, and a row's tenant is
    exactly what a tenant-scoped session cannot look up. The same shape that
    solved that for claims solves it here — a definer function owned by
    ``akc_claim_broker`` with a fixed return surface — with two differences that
    follow from a callback not being a claim: it stamps no lease, so it returns
    none, and it is read-only, so calling it twice changes nothing.

    ``None`` means the row is not a callback target: it does not exist, or the
    provider was never given it. Both are the same answer to the caller, and
    neither is an error — an unknown callback is a thing to decline, not to
    crash on.
    """

    _validate_function(function, prefix=_RESOLVER_NAME_PREFIX)
    await enter_control_plane_context(handle, purpose=purpose)
    result = await handle.execute(
        text(f"SELECT * FROM {function}(:invocation_id)"),  # noqa: S608 - validated identifier
        {"invocation_id": str(invocation_id)},
    )
    row = result.mappings().first()
    if row is None:
        return None
    if tuple(row.keys()) != CALLBACK_RESOLVER_RETURN_COLUMNS:
        raise ClaimBrokerContractViolation(
            f"callback_resolver_surface_changed:{function}:{','.join(row.keys())}"
        )
    return WorkerCallback(
        callback_id=uuid.UUID(str(row["callback_id"])),
        tenant_id=uuid.UUID(str(row["tenant_id"])),
        project_id=_coerce_optional(row["project_id"]),
    )


async def claim_backlog(
    handle: AsyncSession | AsyncConnection,
    *,
    function: str,
    purpose: str = "claim",
) -> tuple[int, int]:
    """``(backlog, claimable)`` for one queue, from the two probes beside its broker.

    Counts and nothing else — both probes carry the same purpose gate as the
    broker, so neither is a way around it. Taken together in one call because
    comparing them is the only thing either is for: a claimable count on its own
    cannot tell a queue this worker cannot see from one whose rows are all
    legitimately leased.
    """

    _validate_function(function)
    await enter_control_plane_context(handle, purpose=purpose)
    backlog = await handle.scalar(text(f"SELECT {function}_backlog()"))
    claimable = await handle.scalar(text(f"SELECT {function}_depth()"))
    return int(backlog or 0), int(claimable or 0)


@dataclass
class ClaimStarvationDetector:
    """Distinguish an idle queue from a worker that cannot see its work.

    The signature of RLS starvation is *backlog exists and this worker claims
    nothing, repeatedly*. One empty poll against a non-empty queue is ordinary —
    another worker took the row. A run of them is not.

    ``threshold`` is a count of consecutive empty polls, not a duration, because
    poll intervals differ per worker and the thing being measured is "this
    worker keeps losing", not "time passed".
    """

    threshold: int = 3
    consecutive_zero_polls: int = 0

    def __post_init__(self) -> None:
        if self.threshold < 1:
            raise ValueError("threshold must be at least one poll")

    def observe(
        self,
        *,
        claimed: bool,
        backlog_depth: int,
        claimable_depth: int,
    ) -> ClaimObservation:
        """Classify one poll.

        ``backlog_depth`` is pending work whether or not anybody holds it;
        ``claimable_depth`` is the subset nothing holds. Their difference is
        "pending but leased", and it is the whole reason two counts are taken:
        with only the claimable one, a queue whose every row is legitimately
        leased is indistinguishable from one this worker cannot see.
        """

        if claimed:
            self.consecutive_zero_polls = 0
            return ClaimObservation(
                health=ClaimHealth.HEALTHY,
                backlog_depth=backlog_depth,
                claimable_depth=claimable_depth,
                consecutive_zero_polls=0,
            )
        self.consecutive_zero_polls += 1
        if backlog_depth <= 0:
            # Nothing pending. However long this runs it is not an incident, and
            # a detector that eventually pages on an idle queue gets turned off.
            health = ClaimHealth.IDLE
        elif claimable_depth <= 0:
            # Pending, but all of it is somebody else's lease. Waiting is the
            # correct behaviour and this must not read as starvation.
            health = ClaimHealth.BLOCKED
        elif self.consecutive_zero_polls < self.threshold:
            health = ClaimHealth.CONTENDED
        else:
            health = ClaimHealth.STARVED
        return ClaimObservation(
            health=health,
            backlog_depth=backlog_depth,
            claimable_depth=claimable_depth,
            consecutive_zero_polls=self.consecutive_zero_polls,
        )
