"""Immutable page-attempt identity and append-only lifecycle evidence."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from akc_cir import PageState, page_transition_allowed
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.models import (
    PageAttempt,
    PageAttemptTransitionEvent,
    utcnow,
)

TERMINAL_PAGE_STATES = frozenset(
    {
        PageState.COMPLETED,
        PageState.NEEDS_REVIEW,
        PageState.FAILED,
    }
)


class PageAttemptTransitionError(ValueError):
    """The requested state change violates the canonical page state machine."""


def _bounded_payload(value: dict[str, Any] | None) -> dict[str, Any]:
    payload = value or {}
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > 16 * 1024:
        raise ValueError("page attempt event payload exceeds 16 KiB")
    return payload


async def next_attempt_number(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    page_id: uuid.UUID,
) -> int:
    """Return the next sequence while the caller holds the page row lock."""

    latest = await session.scalar(
        select(func.max(PageAttempt.attempt_number)).where(
            PageAttempt.tenant_id == tenant_id,
            PageAttempt.page_id == page_id,
        )
    )
    return int(latest or 0) + 1


async def create_page_attempt(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    page_id: uuid.UUID,
    attempt_number: int,
    trigger: str,
    initial_state: PageState,
    route: str,
    route_profile: str,
    route_policy_version: str,
    max_attempts: int,
    job_id: uuid.UUID | None = None,
    analysis_task_id: uuid.UUID | None = None,
    quality_vector: dict[str, Any] | None = None,
    quality_findings: Iterable[dict[str, Any]] = (),
    quality_evaluation: dict[str, Any] | None = None,
    escalation_decision: dict[str, Any] | None = None,
    reason: str = "attempt_created",
    payload: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> PageAttempt:
    """Create one attempt and its first immutable lifecycle event."""

    if attempt_number < 1:
        raise ValueError("page attempt numbers start at one")
    if not 1 <= max_attempts <= 5:
        raise ValueError("max_attempts must be 1..5")
    occurred_at = now or utcnow()
    attempt = PageAttempt(
        tenant_id=tenant_id,
        page_id=page_id,
        job_id=job_id,
        analysis_task_id=analysis_task_id,
        attempt_number=attempt_number,
        trigger=trigger,
        status=initial_state.value,
        route=route,
        route_profile=route_profile,
        route_policy_version=route_policy_version,
        max_attempts=max_attempts,
        quality_vector=quality_vector or {},
        quality_findings=list(quality_findings),
        quality_evaluation=quality_evaluation or {},
        escalation_decision=escalation_decision or {},
        event_sequence=1,
        started_at=occurred_at,
        completed_at=(occurred_at if initial_state in TERMINAL_PAGE_STATES else None),
        created_at=occurred_at,
        updated_at=occurred_at,
    )
    session.add(attempt)
    await session.flush()
    event_payload = {
        **_bounded_payload(payload),
        "attempt_id": str(attempt.id),
        "attempt_number": attempt.attempt_number,
        "trigger": trigger,
    }
    session.add(
        PageAttemptTransitionEvent(
            tenant_id=tenant_id,
            attempt_id=attempt.id,
            sequence=1,
            previous_state=None,
            current_state=initial_state.value,
            reason=reason,
            payload=event_payload,
            occurred_at=occurred_at,
        )
    )
    await session.flush()
    return attempt


async def transition_page_attempt(
    session: AsyncSession,
    attempt: PageAttempt,
    target: PageState,
    *,
    reason: str,
    payload: dict[str, Any] | None = None,
    quality_vector: dict[str, Any] | None = None,
    quality_findings: Iterable[dict[str, Any]] | None = None,
    quality_evaluation: dict[str, Any] | None = None,
    escalation_decision: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> PageAttemptTransitionEvent | None:
    """Advance state through the sole production transition boundary."""

    previous = PageState(attempt.status)
    if previous in TERMINAL_PAGE_STATES:
        raise PageAttemptTransitionError(f"terminal page attempt is immutable: {previous.value}")
    if previous == target:
        return None
    if not page_transition_allowed(previous, target):
        raise PageAttemptTransitionError(
            f"illegal page attempt transition: {previous.value}->{target.value}"
        )
    occurred_at = now or utcnow()
    attempt.status = target.value
    attempt.event_sequence += 1
    attempt.updated_at = occurred_at
    if quality_vector is not None:
        attempt.quality_vector = quality_vector
    if quality_findings is not None:
        attempt.quality_findings = list(quality_findings)
    if quality_evaluation is not None:
        attempt.quality_evaluation = quality_evaluation
    if escalation_decision is not None:
        attempt.escalation_decision = escalation_decision
    if target in TERMINAL_PAGE_STATES:
        attempt.completed_at = occurred_at
    event_payload = {
        **_bounded_payload(payload),
        "attempt_id": str(attempt.id),
        "attempt_number": attempt.attempt_number,
    }
    event = PageAttemptTransitionEvent(
        tenant_id=attempt.tenant_id,
        attempt_id=attempt.id,
        sequence=attempt.event_sequence,
        previous_state=previous.value,
        current_state=target.value,
        reason=reason,
        payload=event_payload,
        occurred_at=occurred_at,
    )
    session.add(event)
    await session.flush()
    return event


async def attach_provider_invocation(
    session: AsyncSession,
    attempt: PageAttempt,
    *,
    invocation_id: uuid.UUID,
) -> None:
    """Bind a durable provider request before an attempt becomes terminal."""

    if PageState(attempt.status) in TERMINAL_PAGE_STATES:
        raise PageAttemptTransitionError("terminal page attempt is immutable")
    if attempt.provider_invocation_id not in {None, invocation_id}:
        raise PageAttemptTransitionError("page attempt already has a provider invocation")
    attempt.provider_invocation_id = invocation_id
    attempt.updated_at = utcnow()
    await session.flush()


async def latest_attempts_for_pages(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    page_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, PageAttempt]:
    """Return the newest attempt for each page without dialect-specific SQL."""

    ids = tuple(page_ids)
    if not ids:
        return {}
    rows = list(
        (
            await session.scalars(
                select(PageAttempt)
                .where(
                    PageAttempt.tenant_id == tenant_id,
                    PageAttempt.page_id.in_(ids),
                )
                .order_by(PageAttempt.page_id, PageAttempt.attempt_number.desc())
            )
        ).all()
    )
    latest: dict[uuid.UUID, PageAttempt] = {}
    for row in rows:
        latest.setdefault(row.page_id, row)
    return latest
