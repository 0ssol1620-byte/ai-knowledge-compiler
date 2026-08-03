"""Database and event integration contracts for persistence adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Any

from .identity import canonical_json, canonical_sha256, stable_id

PARALLEL_RUNTIME_TABLES = (
    "parse_shards",
    "parse_attempts",
    "attempt_validations",
    "worker_health",
    "semantic_health_events",
    "continuity_edges",
    "accepted_blocks",
    "recovery_tasks",
    "arbitration_decisions",
)

PARALLEL_RUNTIME_EVENT_TYPES = (
    "shard.planned.v1",
    "shard.dispatched.v1",
    "attempt.started.v1",
    "attempt.output.received.v1",
    "attempt.validation.failed.v1",
    "attempt.accepted.v1",
    "attempt.rejected.v1",
    "attempt.hedged.v1",
    "worker.semantic.degraded.v1",
    "worker.draining.v1",
    "worker.quarantined.v1",
    "recovery.region.requested.v1",
    "recovery.completed.v1",
    "recovery.planned.v1",
    "recovery.started.v1",
    "recovery.validated.v1",
    "region.verified.v1",
    "region.unresolved.v1",
    "worker.semantic.canary_failed.v1",
    "impact.replay.requested.v1",
    "final.accuracy.calculated.v1",
    "trust.receipt.issued.v1",
    "drift.detected.v1",
    "rollback.triggered.v1",
    "quality.finding.created.v1",
    "recovery.plan.created.v1",
    "recovery.attempt.started.v1",
    "recovery.candidate.generated.v1",
    "recovery.validation.completed.v1",
    "recovery.candidate.accepted.v1",
    "recovery.exhausted.v1",
    "knowledge.objects.invalidated.v1",
    "knowledge.objects.regenerated.v1",
    "package.trust_receipt.created.v1",
    "continuity.merge.started.v1",
    "continuity.merge.completed.v1",
    "document.finalized.v1",
)

IDEMPOTENT_OPERATIONS = frozenset(
    {"shard_dispatch", "hedge", "retry", "acceptance", "merge", "credit", "export"}
)


class EventConflictError(RuntimeError):
    """An idempotency key was reused for a different event."""


@dataclass(frozen=True, slots=True)
class DomainEvent:
    event_id: str
    event_type: str
    aggregate_id: str
    sequence: int
    occurred_at: datetime
    payload_json: str
    payload_sha256: str
    idempotency_key: str

    @property
    def payload(self) -> dict[str, Any]:
        """Return a defensive copy; the journal's canonical payload is immutable."""

        value = json.loads(self.payload_json)
        if not isinstance(value, dict):
            raise RuntimeError("domain event payload must decode to an object")
        return value


class EventJournal:
    """Thread-safe append-only journal with aggregate ordering and idempotency."""

    def __init__(self) -> None:
        self._events: list[DomainEvent] = []
        self._keys: dict[str, DomainEvent] = {}
        self._sequences: dict[str, int] = {}
        self._last_occurred_at: dict[str, datetime] = {}
        self._lock = RLock()

    def append(
        self,
        *,
        event_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
        occurred_at: datetime,
        idempotency_key: str,
    ) -> DomainEvent:
        if event_type not in PARALLEL_RUNTIME_EVENT_TYPES:
            raise ValueError(f"unsupported parallel runtime event type: {event_type}")
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("event occurred_at must be timezone-aware")
        payload_copy = dict(payload)
        digest = canonical_sha256(payload_copy)
        event_identity = canonical_sha256(
            {"event_type": event_type, "aggregate_id": aggregate_id, "payload": payload_copy}
        )
        with self._lock:
            existing = self._keys.get(idempotency_key)
            if existing is not None:
                if canonical_sha256(
                    {
                        "event_type": existing.event_type,
                        "aggregate_id": existing.aggregate_id,
                        "payload": existing.payload,
                    }
                ) != event_identity:
                    raise EventConflictError("idempotency key reused with a different event")
                return existing
            previous_occurred_at = self._last_occurred_at.get(aggregate_id)
            if previous_occurred_at is not None and occurred_at < previous_occurred_at:
                raise ValueError("aggregate events must be chronological")
            sequence = self._sequences.get(aggregate_id, 0) + 1
            event = DomainEvent(
                event_id=stable_id("evt", event_type, aggregate_id, idempotency_key, digest),
                event_type=event_type,
                aggregate_id=aggregate_id,
                sequence=sequence,
                occurred_at=occurred_at,
                payload_json=canonical_json(payload_copy),
                payload_sha256=digest,
                idempotency_key=idempotency_key,
            )
            self._events.append(event)
            self._keys[idempotency_key] = event
            self._sequences[aggregate_id] = sequence
            self._last_occurred_at[aggregate_id] = occurred_at
            return event

    def events(self, *, aggregate_id: str | None = None) -> tuple[DomainEvent, ...]:
        with self._lock:
            if aggregate_id is None:
                return tuple(self._events)
            return tuple(event for event in self._events if event.aggregate_id == aggregate_id)


__all__ = [
    "IDEMPOTENT_OPERATIONS",
    "PARALLEL_RUNTIME_EVENT_TYPES",
    "PARALLEL_RUNTIME_TABLES",
    "DomainEvent",
    "EventConflictError",
    "EventJournal",
]
