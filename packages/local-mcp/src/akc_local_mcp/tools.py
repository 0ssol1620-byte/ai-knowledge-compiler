"""The three read-only knowledge tools and their fail-closed contract.

Contract A (blueprint §2, mirrored from `docs/architecture/canonical-ir.md`):
**UNRESOLVED never silently becomes CURRENT.** When the world state is absent,
unreadable, or does not contain what was asked for, a tool answers
`{"status": "UNRESOLVED", ...}` with a reason — it does not raise a generic
error into the conversation, guess a nearest match, or serve an empty answer
that could be mistaken for "nothing is wrong". The asymmetry decides: an
unanswered question costs one retry, while a quietly stale or fabricated answer
ships a wrong conclusion.

Tools defined here (all reads over `LocalWorldStore`):

- `get_current_truth(topic)`    — one topic's compiled truth plus its claims.
- `get_evidence(claim_id)`      — one claim's evidence chain.
- `search_world(query, limit)`  — substring search across topics and claims.

There are deliberately no write-shaped counterparts. What may not exist here is
listed in `akc_local_mcp.server`'s module docstring; none of it can be
registered by accident because the tool surface below is exhaustive.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .store import (
    ClaimRecord,
    LocalWorldStore,
    StoreError,
    TopicRecord,
    UnknownWorldError,
    WorldDocumentError,
    WorldSnapshot,
)

__all__ = [
    "ReasonCode",
    "ToolResponse",
    "WorldRef",
    "get_current_truth",
    "get_evidence",
    "search_world",
]

STATUS_CURRENT = "CURRENT"
STATUS_UNRESOLVED = "UNRESOLVED"


class ReasonCode(StrEnum):
    """Why a question could not be answered from the published world."""

    WORLD_STATE_UNAVAILABLE = "WORLD_STATE_UNAVAILABLE"
    TOPIC_NOT_FOUND = "TOPIC_NOT_FOUND"
    CLAIM_NOT_FOUND = "CLAIM_NOT_FOUND"
    NO_MATCHES = "NO_MATCHES"
    INVALID_INPUT = "INVALID_INPUT"


@dataclass(frozen=True, slots=True)
class WorldRef:
    """Which published world an answer was computed against. Makes it citable."""

    world_id: str
    manifest_hash: str

    def to_dict(self) -> dict[str, str]:
        return {"world_id": self.world_id, "manifest_hash": self.manifest_hash}


@dataclass(frozen=True, slots=True)
class ToolResponse:
    """What a tool returns: either CURRENT with a payload, or UNRESOLVED."""

    resolved: bool
    message: str
    payload: Mapping[str, Any]
    reason_code: ReasonCode | None = None

    @classmethod
    def unresolved(cls, reason_code: ReasonCode, message: str) -> ToolResponse:
        return cls(resolved=False, message=message, payload={}, reason_code=reason_code)

    @classmethod
    def current(cls, message: str, **payload: Any) -> ToolResponse:
        return cls(resolved=True, message=message, payload=payload)

    @property
    def status(self) -> str:
        return STATUS_CURRENT if self.resolved else STATUS_UNRESOLVED

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "message": self.message,
            **self.payload,
        }
        if self.reason_code is not None:
            result["reason"] = {"code": str(self.reason_code.value)}
        return result


@dataclass(frozen=True, slots=True)
class _SelectionFailure:
    reason_code: ReasonCode
    message: str


_SnapshotResult = tuple[WorldSnapshot | None, _SelectionFailure | None]
_SelectionResult = tuple[WorldRef | None, _SelectionFailure | None]


def _clean(value: str) -> str:
    return value.strip()


def _select_active_world(store: LocalWorldStore) -> _SelectionResult:
    """Pick the single ACTIVE world, or say precisely why there isn't one."""
    if not store.root.is_dir():
        return None, _SelectionFailure(
            ReasonCode.WORLD_STATE_UNAVAILABLE,
            f"the configured world-state directory does not exist: {store.root}",
        )
    try:
        manifests = store.list_worlds()
    except StoreError as exc:
        return None, _SelectionFailure(ReasonCode.WORLD_STATE_UNAVAILABLE, str(exc))
    active = [manifest for manifest in manifests if manifest.status == "ACTIVE"]
    if len(active) == 1:
        return WorldRef(world_id=active[0].world_id, manifest_hash=active[0].manifest_hash), None
    if not active:
        listed = ", ".join(sorted(m.world_id for m in manifests)) or "none"
        return None, _SelectionFailure(
            ReasonCode.WORLD_STATE_UNAVAILABLE,
            f"no ACTIVE world state under {store.root} (found: {listed}); "
            "a world that has not been published cannot be quoted",
        )
    names = ", ".join(sorted(m.world_id for m in active))
    return None, _SelectionFailure(
        ReasonCode.WORLD_STATE_UNAVAILABLE,
        f"multiple ACTIVE world states ({names}); refusing to pick one silently",
    )


def _load_snapshot(store: LocalWorldStore, ref: WorldRef) -> _SnapshotResult:
    try:
        return store.load_snapshot(ref.world_id), None
    except (UnknownWorldError, WorldDocumentError) as exc:
        return None, _SelectionFailure(ReasonCode.WORLD_STATE_UNAVAILABLE, str(exc))


def get_current_truth(store: LocalWorldStore, topic: str) -> ToolResponse:
    """Read the current-truth record for one topic from the ACTIVE world.

    UNRESOLVED when there is no readable ACTIVE world, or no topic matches
    `topic` exactly (by id) or uniquely (by case-insensitive title).
    """
    cleaned = _clean(topic)
    if not cleaned:
        return ToolResponse.unresolved(ReasonCode.INVALID_INPUT, "topic must be a non-empty string")
    ref, failure = _select_active_world(store)
    if ref is None or failure is not None:
        assert failure is not None
        return ToolResponse.unresolved(failure.reason_code, failure.message)
    snapshot, load_failure = _load_snapshot(store, ref)
    if snapshot is None or load_failure is not None:
        assert load_failure is not None
        return ToolResponse.unresolved(load_failure.reason_code, load_failure.message)

    needle = cleaned.casefold()
    exact = [t for t in snapshot.topics if t.topic_id == cleaned]
    by_title = [t for t in snapshot.topics if t.title.casefold() == needle]
    candidates = exact or by_title
    if not candidates:
        return ToolResponse.unresolved(
            ReasonCode.TOPIC_NOT_FOUND,
            f"world {ref.world_id!r} has no topic matching {cleaned!r}; "
            f"available topics: {', '.join(sorted(t.topic_id for t in snapshot.topics)) or 'none'}",
        )
    if len(candidates) > 1:
        ids = ", ".join(sorted(t.topic_id for t in candidates))
        return ToolResponse.unresolved(
            ReasonCode.TOPIC_NOT_FOUND,
            f"several topics match {cleaned!r} ({ids}); refusing to choose silently",
        )
    record: TopicRecord = candidates[0]
    claims_by_id = {claim.claim_id: claim for claim in snapshot.claims}
    claims = [claims_by_id[cid].to_dict() for cid in record.claim_ids if cid in claims_by_id]
    return ToolResponse.current(
        f"current truth for topic {record.topic_id!r} in world {ref.world_id!r}",
        topic=record.to_dict(),
        claims=claims,
        world=ref.to_dict(),
    )


def get_evidence(store: LocalWorldStore, claim_id: str) -> ToolResponse:
    """Return one claim's evidence chain from the ACTIVE world.

    UNRESOLVED when there is no readable ACTIVE world or the claim id is not
    part of it. A missing evidence chain is reported as such inside a CURRENT
    answer only because the claim itself exists; an unknown claim id stays
    UNRESOLVED.
    """
    cleaned = _clean(claim_id)
    if not cleaned:
        return ToolResponse.unresolved(
            ReasonCode.INVALID_INPUT, "claim_id must be a non-empty string"
        )
    ref, failure = _select_active_world(store)
    if ref is None or failure is not None:
        assert failure is not None
        return ToolResponse.unresolved(failure.reason_code, failure.message)
    snapshot, load_failure = _load_snapshot(store, ref)
    if snapshot is None or load_failure is not None:
        assert load_failure is not None
        return ToolResponse.unresolved(load_failure.reason_code, load_failure.message)

    matches = [claim for claim in snapshot.claims if claim.claim_id == cleaned]
    if not matches:
        known = sorted(claim.claim_id for claim in snapshot.claims)
        return ToolResponse.unresolved(
            ReasonCode.CLAIM_NOT_FOUND,
            f"claim {cleaned!r} does not exist in world {ref.world_id!r}; "
            f"known claims: {', '.join(known) or 'none'}",
        )
    claim: ClaimRecord = matches[0]
    return ToolResponse.current(
        f"evidence for claim {claim.claim_id!r} in world {ref.world_id!r}",
        claim=claim.to_dict(),
        world=ref.to_dict(),
    )


def search_world(store: LocalWorldStore, query: str, *, limit: int = 10) -> ToolResponse:
    """Case-insensitive substring search across topics and claims.

    Zero hits is itself answered UNRESOLVED (`NO_MATCHES`): a search that found
    nothing must not be presented as an affirmative result. Results are capped
    at `limit`, most specific field first, deterministically ordered.
    """
    cleaned = _clean(query)
    if not cleaned:
        return ToolResponse.unresolved(ReasonCode.INVALID_INPUT, "query must be a non-empty string")
    if limit <= 0:
        return ToolResponse.unresolved(ReasonCode.INVALID_INPUT, "limit must be a positive integer")
    ref, failure = _select_active_world(store)
    if ref is None or failure is not None:
        assert failure is not None
        return ToolResponse.unresolved(failure.reason_code, failure.message)
    snapshot, load_failure = _load_snapshot(store, ref)
    if snapshot is None or load_failure is not None:
        assert load_failure is not None
        return ToolResponse.unresolved(load_failure.reason_code, load_failure.message)

    needle = cleaned.casefold()

    def hit(kind: str, entry_id: str, field: str, text: str) -> dict[str, str]:
        start = text.casefold().find(needle)
        begin = max(start - 40, 0)
        snippet = ("…" if begin > 0 else "") + text[begin : start + len(cleaned) + 60]
        return {
            "kind": kind,
            "id": entry_id,
            "matched_in": field,
            "snippet": snippet + ("…" if start + len(cleaned) + 60 < len(text) else ""),
        }

    hits: list[tuple[tuple[int, str], dict[str, str]]] = []
    field_rank = {"id": 0, "title": 1, "keyword": 2, "summary": 3, "status": 4, "text": 5}
    for record in snapshot.topics:
        for field, value in (
            ("id", record.topic_id),
            ("title", record.title),
            ("keyword", " ".join(record.keywords)),
            ("summary", record.summary),
        ):
            if needle in value.casefold():
                key = (field_rank[field], record.topic_id)
                hits.append((key, hit("topic", record.topic_id, field, value)))
    for claim in snapshot.claims:
        for field, value in (
            ("id", claim.claim_id),
            ("text", claim.text),
            ("status", claim.status),
        ):
            if needle in value.casefold():
                key = (field_rank[field], claim.claim_id)
                hits.append((key, hit("claim", claim.claim_id, field, value)))

    if not hits:
        return ToolResponse.unresolved(
            ReasonCode.NO_MATCHES,
            f"nothing in world {ref.world_id!r} matches {cleaned!r}",
        )
    hits.sort(key=lambda pair: pair[0])
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for _, entry in hits:
        identity = (entry["kind"], entry["id"], entry["matched_in"])
        if identity not in seen:
            seen.add(identity)
            deduped.append(entry)
    return ToolResponse.current(
        f"{len(deduped)} match(es) for {cleaned!r} in world {ref.world_id!r}"
        + (f" (showing first {limit})" if len(deduped) > limit else ""),
        query=cleaned,
        hits=deduped[:limit],
        world=ref.to_dict(),
    )
