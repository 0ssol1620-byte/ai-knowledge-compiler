"""Trial session expiry — ADR-006.

The one-hour lifetime is the main thing standing between an anonymous public
endpoint and unbounded storage. A cap nothing enforces is a comment, so this is
the code that makes it true.

The sweep marks expired sessions and their documents as deletion-requested,
which is the same signal the authenticated deletion lifecycle already acts on
(ADR-004, ``deletions.py``). It does not invent a second deletion path: objects
are removed by the machinery that already knows how to remove them, with the
same receipts.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.models import Document, Project, TrialSession, utcnow

logger = logging.getLogger(__name__)

# Reserved tenant from migration 0023.
TRIAL_TENANT_ID = uuid.UUID("00000000-0000-4000-a000-000000000b01")


async def sweep_expired_trial_sessions(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    batch_size: int = 200,
) -> int:
    """Retire every trial session past its expiry. Returns how many were retired.

    Bounded per call so a backlog cannot turn one pass into an unbounded
    transaction; the scheduler calls it again on the next tick.

    Adopted sessions are skipped. Adoption moved the work into a real tenant
    with that tenant's retention policy, and expiring it here would delete a
    document its owner is entitled to keep.
    """
    moment = now or utcnow()

    expired = (
        await session.scalars(
            select(TrialSession)
            .where(
                TrialSession.tenant_id == TRIAL_TENANT_ID,
                TrialSession.deletion_requested_at.is_(None),
                TrialSession.adopted_tenant_id.is_(None),
                TrialSession.expires_at <= moment,
            )
            .order_by(TrialSession.expires_at)
            .limit(batch_size)
        )
    ).all()

    if not expired:
        return 0

    project_ids = [trial.project_id for trial in expired]

    # Documents first. A document marked before its project cannot be read by a
    # request that arrives mid-sweep; the other order leaves a window where the
    # project is gone but the document is still answerable.
    await session.execute(
        update(Document)
        .where(
            Document.tenant_id == TRIAL_TENANT_ID,
            Document.project_id.in_(project_ids),
            Document.deletion_requested_at.is_(None),
        )
        .values(deletion_requested_at=moment)
    )
    await session.execute(
        update(Project)
        .where(
            Project.tenant_id == TRIAL_TENANT_ID,
            Project.id.in_(project_ids),
            Project.deletion_requested_at.is_(None),
        )
        .values(deletion_requested_at=moment)
    )
    await session.execute(
        update(TrialSession)
        .where(TrialSession.id.in_([trial.id for trial in expired]))
        .values(deletion_requested_at=moment)
    )
    await session.commit()

    logger.info("trial retention: retired %d expired session(s)", len(expired))
    return len(expired)


def is_expired(expires_at: datetime, *, now: datetime | None = None) -> bool:
    """Shared expiry predicate.

    Columns are ``DateTime(timezone=True)`` but SQLite returns naive values, so
    the comparison is normalised rather than left to depend on which driver is
    underneath.
    """
    moment = now or utcnow()
    aware = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=UTC)
    return aware <= moment
