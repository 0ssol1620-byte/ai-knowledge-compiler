"""Canary B — remove BYPASSRLS from the GPU worker, in staging, on request only.

**This migration does nothing unless it is explicitly asked to.** It reads
``AKC_CANARY_B_DISARM_GPU`` and is a no-op without it. That is not timidity: a
migration that disarms on sight would disarm production the moment it deployed,
and the whole point of a canary is that one environment moves first. CI, dev and
production all run this and all stay at ``BYPASSRLS`` 7/7.

Revision numbering was reconciled against the live chain rather than against the
older plan documents, which assumed ``0036_control_plane_column_grants`` and
``0037_disarm_payment_worker``. ``0036`` is taken by ``0036_claim_backlog_probe``
and the payment worker is not first any more; the plan's numbering is stale and
is corrected in ``V5_WORKER_AUTHZ_DECISION_PACKAGE.md`` §10 in the same change.

**One role. Six others keep the attribute**, and the downgrade restores this one
unconditionally, so rollback is a single statement in either direction.

---

**READ BEFORE RUNNING THIS. A measured blocker stands in front of it.**

Applying this today makes the GPU worker claim successfully and then fail to do
the work, silently. Measured on a throwaway PG17 cluster at
``0036_claim_backlog_probe``:

    post-claim session, tenant bound only (what the code does now):  0 rows
    same session with tenant + project + claim + lease bound:        1 row

``GpuInvocationWorker._locked_invocation`` is the funnel for every post-claim
read and write, and it binds only ``app.tenant_id``. The claim-binding policy
from ``0034`` admits a row when the session is in discovery (no tenant, no
claim) or holds the full claim; a tenant on its own satisfies neither. So every
post-claim statement sees nothing, ``_locked_invocation`` returns ``None``, and
the worker reads that as a lost lease and abandons the job.

**Gate 1 does not catch this**, which is the dangerous part. The claim itself
succeeds through the broker, so the starvation detector sees ``claimed=True``
and resets. The queue would drain into rows that are claimed, leased and never
progressed — a worker that runs and does no work, which is exactly what "the
worker runs is not a PASS" was written about.

Two things are missing before Canary B can pass, and neither is in this file:

1. ``_Claim`` carries no ``project_id`` and no ``lease_expires_at``, so
   ``enter_claim_context`` cannot be called at ``_locked_invocation`` yet.
2. ``_locked_invocation`` must bind the claim rather than the tenant.

Until both land, running this migration produces a RED canary with a known
cause. The rollback is ``infra/postgres/canary_b_rollback.py`` or the downgrade
below.

Revision ID: 0037_canary_b_disarm_gpu_worker
Revises: 0036_claim_backlog_probe
"""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

revision = "0037_canary_b_disarm_gpu_worker"
down_revision = "0036_claim_backlog_probe"
branch_labels = None
depends_on = None

# The one role this migration may touch. Named as a constant so a future edit
# that adds a second role is a visible diff rather than a loop bound.
CANARY_ROLE = "akc_gpu_worker"

# The opt-in. Anything other than exactly "1" leaves the cluster alone.
OPT_IN = "AKC_CANARY_B_DISARM_GPU"

_ROLE_STATE = """
SELECT rolbypassrls FROM pg_roles WHERE rolname = :role
"""


def _requested() -> bool:
    return os.environ.get(OPT_IN, "").strip() == "1"


def _bypassrls_holders() -> list[str]:
    rows = op.get_bind().execute(
        text(
            "SELECT rolname FROM pg_roles "
            "WHERE rolname LIKE 'akc\\_%' ESCAPE '\\' AND rolbypassrls "
            "ORDER BY rolname"
        )
    )
    return [str(row[0]) for row in rows]


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    if not _requested():
        print(
            f"0037: {OPT_IN} is not set to 1 — leaving {CANARY_ROLE} armed. "
            "This is the expected outcome everywhere except the staging canary."
        )
        return

    state = op.get_bind().execute(text(_ROLE_STATE), {"role": CANARY_ROLE}).scalar()
    if state is None:
        raise RuntimeError(f"{CANARY_ROLE} does not exist; refusing to guess")

    op.execute(f"ALTER ROLE {CANARY_ROLE} NOBYPASSRLS")

    # Assert the blast radius rather than trusting the statement above: exactly
    # one role left the set, and it was this one.
    holders = _bypassrls_holders()
    if CANARY_ROLE in holders:
        raise RuntimeError(f"{CANARY_ROLE} still holds BYPASSRLS after the ALTER")
    if len(holders) != 6:
        raise RuntimeError(
            f"expected 6 remaining BYPASSRLS holders, found {len(holders)}: {holders}"
        )
    print(f"0037: {CANARY_ROLE} disarmed for canary B; {len(holders)} roles still armed")


def downgrade() -> None:
    """Restore the attribute unconditionally.

    No opt-in guard here, deliberately. Rollback must work whether or not the
    environment that is rolling back is the one that opted in, and re-granting
    an attribute the role already holds costs nothing.
    """

    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER ROLE {CANARY_ROLE} BYPASSRLS")
    holders = _bypassrls_holders()
    if CANARY_ROLE not in holders:
        raise RuntimeError(f"{CANARY_ROLE} did not regain BYPASSRLS")
    print(f"0037: {CANARY_ROLE} rearmed; {len(holders)} roles armed")
