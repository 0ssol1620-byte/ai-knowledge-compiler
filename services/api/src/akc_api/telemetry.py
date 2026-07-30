"""Transaction-aware domain metric hooks."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from akc_telemetry import AUDIT_WRITE_FAILURE
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
_PENDING_KEY = "akc_pending_metric_calls"
_AUDIT_PENDING_KEY = "akc_audit_write_pending"
MetricCall = tuple[Callable[..., None], tuple[Any, ...], dict[str, Any]]


def after_commit_metric(
    session: AsyncSession,
    callback: Callable[..., None],
    /,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Run a content-free metric update only after the DB transaction commits."""

    pending = session.info.setdefault(_PENDING_KEY, [])
    pending.append((callback, args, kwargs))


def track_audit_write(session: AsyncSession) -> None:
    """Mark the transaction as containing an audit record."""

    session.info[_AUDIT_PENDING_KEY] = True


@event.listens_for(Session, "after_commit")
def _record_committed_metrics(session: Session) -> None:
    session.info.pop(_AUDIT_PENDING_KEY, None)
    pending: list[MetricCall] = session.info.pop(_PENDING_KEY, [])
    for callback, args, kwargs in pending:
        try:
            callback(*args, **kwargs)
        except Exception:
            logger.warning("committed metric callback failed", exc_info=False)


@event.listens_for(Session, "after_rollback")
def _discard_rolled_back_metrics(session: Session) -> None:
    if session.info.pop(_AUDIT_PENDING_KEY, False):
        AUDIT_WRITE_FAILURE.inc()
    session.info.pop(_PENDING_KEY, None)
