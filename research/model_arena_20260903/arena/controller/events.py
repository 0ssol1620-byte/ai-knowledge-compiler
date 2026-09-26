"""Append-only campaign event log (ARENA_CONTRACT section 3.2, MP section 33).

Every state transition of the campaign, a model, a shard, a worker or a job is
appended here before anything else observes it. The log is the record that
answers "what did the controller believe, and when" after the pods are gone.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from arena.constants import CAMPAIGN_ID
from arena.provider.safety import utc_now_iso, write_jsonl_append

__all__ = ["ENTITY_KINDS", "EventLog", "StateEvent"]

ENTITY_KINDS: Final = ("campaign", "model", "shard", "worker", "job")
SCHEMA: Final = "tavonel.arena.event.v1"


@dataclass(frozen=True, slots=True)
class StateEvent:
    entity_kind: str
    entity_id: str
    from_state: str | None
    to_state: str
    reason: str
    ts: str
    detail: Mapping[str, object] = field(default_factory=dict)
    campaign_id: str = CAMPAIGN_ID

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "campaign_id": self.campaign_id,
            "ts": self.ts,
            "entity_kind": self.entity_kind,
            "entity_id": self.entity_id,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "reason": self.reason,
            "detail": dict(self.detail),
        }


class EventLog:
    """Writes ``receipts/events.jsonl`` and mirrors into the queue if given."""

    def __init__(self, path: Path, *, campaign_id: str = CAMPAIGN_ID) -> None:
        self.path = path
        self.campaign_id = campaign_id
        self._mirror: list[StateEvent] = []

    def append(
        self,
        *,
        entity_kind: str,
        entity_id: str,
        to_state: str,
        reason: str,
        from_state: str | None = None,
        detail: Mapping[str, object] | None = None,
    ) -> StateEvent:
        if entity_kind not in ENTITY_KINDS:
            raise ValueError(f"entity_kind must be one of {ENTITY_KINDS}")
        if not entity_id:
            raise ValueError("entity_id is required")
        event = StateEvent(
            entity_kind=entity_kind,
            entity_id=entity_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            ts=utc_now_iso(),
            detail=dict(detail or {}),
            campaign_id=self.campaign_id,
        )
        # write_jsonl_append runs the secret-free guard before the line lands.
        write_jsonl_append(self.path, event.to_dict(), context="campaign event")
        self._mirror.append(event)
        return event

    @property
    def written(self) -> tuple[StateEvent, ...]:
        """Events appended by this process, in order."""

        return tuple(self._mirror)
