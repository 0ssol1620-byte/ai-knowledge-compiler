"""Durable-path loser handling once a shard has a verified winner (F30-05).

The in-memory ``AttemptStore`` supersedes a loser only when the loser itself
calls ``accept()``; nothing stops a sibling that is still running and billing.
``supersede_losers`` closes that on the SQL path: every non-terminal sibling
attempt of the shard moves to SUPERSEDED and its provider invocation, if still
live, is put in ``cancel_requested`` so the existing ``gpu_jobs`` claim loop
sends the provider cancel. It requests; it does not prove the provider stopped
or stopped billing.

Flush-only: the caller owns the transaction and the commit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from akc_api.gpu_jobs import append_gpu_event
from akc_api.models import GpuProviderInvocation
from akc_api.parallel_models import ParallelParseAttempt, ParallelParseShard
from akc_api.parallel_runtime_store import ParallelRuntimeConflict, transition_parse_attempt
from akc_security.tenant_context import enter_tenant_context
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

SUPERSEDE_REASON = "superseded_by_verified_winner"
_LIVE_ATTEMPT_STATES = ("CREATED", "QUEUED", "RUNNING", "OUTPUT_RECEIVED", "VALIDATING")
_TERMINAL_INVOCATION_STATES = frozenset({"completed", "failed", "dead_letter", "cancelled"})
_CANCEL_STATES = frozenset({"cancel_requested", "cancelling"})


class FirstVerifiedSettlementError(ValueError):
    """The shard, winner or operation key is not a valid settlement target."""


@dataclass(frozen=True, slots=True)
class LoserSettlement:
    superseded_attempt_ids: tuple[uuid.UUID, ...]
    cancel_requested_invocation_ids: tuple[uuid.UUID, ...]
    # Live siblings the attempt state machine does not allow to go SUPERSEDED
    # from their current state (see ``_ATTEMPT_TRANSITIONS``). Left untouched.
    unsupersedable_attempt_ids: tuple[uuid.UUID, ...]


async def supersede_losers(
    session: AsyncSession,
    scope: uuid.UUID,
    shard_id: uuid.UUID,
    winner_attempt_id: uuid.UUID,
    operation_key: str,
    *,
    now: datetime,
) -> LoserSettlement:
    """Supersede the non-terminal siblings of an ACCEPTED winner; idempotent.

    ``scope`` is the tenant id. Idempotency rests on state, not on
    ``operation_key`` (which is only validated and copied into the event
    payload): a replay, under any key, finds no live sibling and no cancellable
    invocation, so it changes nothing.

    Lock order is attempt rows first, then invocation rows; sibling attempts are
    locked before the state-machine check so a concurrent callback's terminal
    state is never overwritten.
    """

    if not operation_key or len(operation_key) > 120:
        raise FirstVerifiedSettlementError("operation_key must be 1..120 characters")
    await enter_tenant_context(session, tenant_id=scope)
    shard = await session.scalar(
        select(ParallelParseShard.id).where(
            ParallelParseShard.tenant_id == scope, ParallelParseShard.id == shard_id
        )
    )
    if shard is None:
        raise FirstVerifiedSettlementError("shard is outside the tenant scope")
    winner = await session.scalar(
        select(ParallelParseAttempt)
        .where(
            ParallelParseAttempt.tenant_id == scope,
            ParallelParseAttempt.shard_id == shard_id,
            ParallelParseAttempt.id == winner_attempt_id,
        )
        .with_for_update()
    )
    if winner is None or winner.state != "ACCEPTED":
        raise FirstVerifiedSettlementError("winner is not an ACCEPTED attempt of this shard")

    siblings = (
        await session.scalars(
            select(ParallelParseAttempt)
            .where(
                ParallelParseAttempt.tenant_id == scope,
                ParallelParseAttempt.shard_id == shard_id,
                ParallelParseAttempt.id != winner_attempt_id,
                ParallelParseAttempt.state.in_(_LIVE_ATTEMPT_STATES),
            )
            .order_by(ParallelParseAttempt.attempt_number)
            .with_for_update()
        )
    ).all()
    superseded: list[uuid.UUID] = []
    cancelled: list[uuid.UUID] = []
    skipped: list[uuid.UUID] = []
    for attempt in siblings:
        try:
            await transition_parse_attempt(session, attempt, "SUPERSEDED", now=now)
        except ParallelRuntimeConflict:
            skipped.append(attempt.id)
        else:
            attempt.failure_domain = "cancelled"
            attempt.failure_code = SUPERSEDE_REASON
            superseded.append(attempt.id)
        if attempt.provider_invocation_id is None:
            continue
        invocation = await session.scalar(
            select(GpuProviderInvocation)
            .where(
                GpuProviderInvocation.tenant_id == scope,
                GpuProviderInvocation.id == attempt.provider_invocation_id,
            )
            .with_for_update()
        )
        if (
            invocation is None
            or invocation.status in _TERMINAL_INVOCATION_STATES
            or invocation.status in _CANCEL_STATES
        ):
            continue
        invocation.status = "cancel_requested"
        # Same as request_gpu_cancellation: drop the lease so a worker mid-poll
        # fails its lease check instead of writing running/submitted back over us.
        invocation.lease_token = None
        invocation.lease_expires_at = None
        invocation.cancellation_reason = SUPERSEDE_REASON
        invocation.available_at = now
        invocation.updated_at = now
        await append_gpu_event(
            session,
            invocation,
            event_type="gpu.invocation.cancel_requested.v1",
            payload={"reason": SUPERSEDE_REASON, "operation_key": operation_key},
            occurred_at=now,
        )
        cancelled.append(invocation.id)
    await session.flush()
    return LoserSettlement(tuple(superseded), tuple(cancelled), tuple(skipped))
