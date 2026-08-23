"""The read-only knowledge surface and its fail-closed contract.

Contract A (blueprint §2, mirrored from `docs/architecture/canonical-ir.md`):
**UNRESOLVED never silently becomes CURRENT.** When the world state is absent,
unreadable, or does not contain what was asked for, a tool answers
`{"status": "UNRESOLVED", ...}` with a reason — it does not raise a generic
error into the conversation, guess a nearest match, or serve an empty answer
that could be mistaken for "nothing is wrong". The asymmetry decides: an
unanswered question costs one retry, while a quietly stale or fabricated answer
ships a wrong conclusion.

Tools defined here (all reads over `LocalWorldStore`):

- `get_current_truth(topic)`     — one topic's compiled truth plus its claims.
- `get_evidence(claim_id)`       — one claim's evidence chain.
- `search_world(query, limit)`   — substring search across topics and claims.
- `ask_as_of(topic, as_of_date)` — the truth for one topic *as it stood* at a
  past point in time, answered from the newest publishable world on disk whose
  `built_at` falls on or before the asked-for moment.
- `get_entity(entity_id)`        — one resolved entity and its claims.
- `get_claim(claim_id)`          — one claim's compiled record.
- `get_change(change_id | source_path)` — one recorded source change.
- `trace_impact(id, direction)`  — the blast radius of changing one node,
  walked over the world's dependency edges (`akc_cir.dependency`).
- `get_world([world_id])`        — one world's manifest and composition, or the
  ACTIVE world when no id is given.
- `compare_worlds(world_a, world_b)` — claim-level diff between two worlds:
  added, removed, and value-changed, field by field.

Every answer is **world-stamped**: `world_state_id`, `freshness` (the world's
`built_at`), and explicit `limitations` ride along with `status`, so a caller
can cite — or refuse to cite — exactly the state an answer came from. An
UNRESOLVED answer carries the stamp too, with nulls where no world could be
selected and a limitation saying why.

There are deliberately no write-shaped counterparts. What may not exist here is
listed in `akc_local_mcp.server`'s module docstring; none of it can be
registered by accident because the tool surface below is exhaustive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from akc_cir.dependency import DependencyEdge, DependencyGraph

from .store import (
    ClaimRecord,
    LocalWorldStore,
    StoreError,
    TopicRecord,
    UnknownWorldError,
    WorldDocumentError,
    WorldManifest,
    WorldSnapshot,
    parse_timestamp,
)

__all__ = [
    "ReasonCode",
    "ToolResponse",
    "WorldRef",
    "ask_as_of",
    "compare_worlds",
    "get_change",
    "get_claim",
    "get_current_truth",
    "get_entity",
    "get_evidence",
    "get_world",
    "search_world",
    "trace_impact",
]

STATUS_CURRENT = "CURRENT"
STATUS_UNRESOLVED = "UNRESOLVED"

#: Statuses a world must carry to be quotable as "the truth at time T".
#: ACTIVE is today's truth; SUPERSEDED was published truth once and is exactly
#: what an as-of question needs. BUILDING/CANDIDATE were never promoted,
#: REJECTED was refused, ROLLED_BACK was withdrawn — none may be quoted.
PUBLISHABLE_STATUSES = frozenset({"ACTIVE", "SUPERSEDED"})


class ReasonCode(StrEnum):
    """Why a question could not be answered from the published world."""

    WORLD_STATE_UNAVAILABLE = "WORLD_STATE_UNAVAILABLE"
    TOPIC_NOT_FOUND = "TOPIC_NOT_FOUND"
    CLAIM_NOT_FOUND = "CLAIM_NOT_FOUND"
    ENTITY_NOT_FOUND = "ENTITY_NOT_FOUND"
    CHANGE_NOT_FOUND = "CHANGE_NOT_FOUND"
    NODE_NOT_FOUND = "NODE_NOT_FOUND"
    WORLD_NOT_FOUND = "WORLD_NOT_FOUND"
    NO_MATCHES = "NO_MATCHES"
    NO_WORLD_AT_DATE = "NO_WORLD_AT_DATE"
    INVALID_INPUT = "INVALID_INPUT"


LIMIT_NO_LIVE_SOURCES = (
    "offline local view: answers come only from what the compiler published "
    "into this world on disk; no live source was consulted"
)
LIMIT_READ_ONLY = "read-only surface: nothing here can modify the world"
LIMIT_NO_WORLD = "no published world could be selected, so nothing could be quoted"


@dataclass(frozen=True, slots=True)
class WorldRef:
    """Which published world an answer was computed against. Makes it citable."""

    world_id: str
    manifest_hash: str

    def to_dict(self) -> dict[str, str]:
        return {"world_id": self.world_id, "manifest_hash": self.manifest_hash}


@dataclass(frozen=True, slots=True)
class ToolResponse:
    """What a tool returns: either CURRENT with a payload, or UNRESOLVED.

    Every response is world-stamped: `world_state_id`, `freshness`, and
    `limitations` are always present in `to_dict()` output — nulls where no
    world backs the answer, never missing keys.
    """

    resolved: bool
    message: str
    payload: dict[str, Any]
    reason_code: ReasonCode | None = None
    world_state_id: str | None = None
    freshness: str | None = None
    limitations: tuple[str, ...] = ()

    @classmethod
    def unresolved(
        cls,
        reason_code: ReasonCode,
        message: str,
        *,
        world_state_id: str | None = None,
        freshness: str | None = None,
        limitations: tuple[str, ...] = (),
    ) -> ToolResponse:
        return cls(
            resolved=False,
            message=message,
            payload={},
            reason_code=reason_code,
            world_state_id=world_state_id,
            freshness=freshness,
            limitations=limitations,
        )

    @classmethod
    def current(
        cls,
        message: str,
        *,
        world_state_id: str | None = None,
        freshness: str | None = None,
        limitations: tuple[str, ...] = (),
        **payload: Any,
    ) -> ToolResponse:
        return cls(
            resolved=True,
            message=message,
            payload=payload,
            world_state_id=world_state_id,
            freshness=freshness,
            limitations=limitations,
        )

    @property
    def status(self) -> str:
        return STATUS_CURRENT if self.resolved else STATUS_UNRESOLVED

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "world_state_id": self.world_state_id,
            "freshness": self.freshness,
            "limitations": list(self.limitations),
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


def _unavailable(message: str) -> ToolResponse:
    return ToolResponse.unresolved(
        ReasonCode.WORLD_STATE_UNAVAILABLE,
        message,
        limitations=(LIMIT_NO_WORLD,),
    )


def _base_limitations() -> tuple[str, ...]:
    return (LIMIT_READ_ONLY, LIMIT_NO_LIVE_SOURCES)


def _resolve_topic(snapshot: WorldSnapshot, cleaned: str) -> tuple[TopicRecord | None, str | None]:
    """Match one topic by exact id or unique case-folded title/id text.

    Returns `(topic, None)` on a unique hit, or `(None, refusal_message)` when
    nothing matches or several things do.
    """
    needle = cleaned.casefold()
    exact = [t for t in snapshot.topics if t.topic_id == cleaned]
    by_text = [
        t
        for t in snapshot.topics
        if t.title.casefold() == needle or t.topic_id.casefold() == needle
    ]
    candidates = exact or by_text
    if not candidates:
        available = ", ".join(sorted(t.topic_id for t in snapshot.topics)) or "none"
        return None, (
            f"world {snapshot.manifest.world_id!r} has no topic matching {cleaned!r}; "
            f"available topics: {available}"
        )
    if len(candidates) > 1:
        ids = ", ".join(sorted(t.topic_id for t in candidates))
        return None, f"several topics match {cleaned!r} ({ids}); refusing to choose silently"
    return candidates[0], None


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
        return _unavailable(failure.message)
    snapshot, load_failure = _load_snapshot(store, ref)
    if snapshot is None or load_failure is not None:
        assert load_failure is not None
        return _unavailable(load_failure.message)

    record, refusal = _resolve_topic(snapshot, cleaned)
    if record is None or refusal is not None:
        assert refusal is not None
        return ToolResponse.unresolved(
            ReasonCode.TOPIC_NOT_FOUND,
            refusal,
            world_state_id=ref.world_id,
            freshness=snapshot.manifest.built_at,
            limitations=_base_limitations(),
        )
    claims_by_id = {claim.claim_id: claim for claim in snapshot.claims}
    claims = [claims_by_id[cid].to_dict() for cid in record.claim_ids if cid in claims_by_id]
    return ToolResponse.current(
        f"current truth for topic {record.topic_id!r} in world {ref.world_id!r}",
        world_state_id=ref.world_id,
        freshness=snapshot.manifest.built_at,
        limitations=_base_limitations(),
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
        return _unavailable(failure.message)
    snapshot, load_failure = _load_snapshot(store, ref)
    if snapshot is None or load_failure is not None:
        assert load_failure is not None
        return _unavailable(load_failure.message)

    matches = [claim for claim in snapshot.claims if claim.claim_id == cleaned]
    if not matches:
        known = sorted(claim.claim_id for claim in snapshot.claims)
        return ToolResponse.unresolved(
            ReasonCode.CLAIM_NOT_FOUND,
            f"claim {cleaned!r} does not exist in world {ref.world_id!r}; "
            f"known claims: {', '.join(known) or 'none'}",
            world_state_id=ref.world_id,
            freshness=snapshot.manifest.built_at,
            limitations=_base_limitations(),
        )
    claim: ClaimRecord = matches[0]
    return ToolResponse.current(
        f"evidence for claim {claim.claim_id!r} in world {ref.world_id!r}",
        world_state_id=ref.world_id,
        freshness=snapshot.manifest.built_at,
        limitations=_base_limitations(),
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
        return _unavailable(failure.message)
    snapshot, load_failure = _load_snapshot(store, ref)
    if snapshot is None or load_failure is not None:
        assert load_failure is not None
        return _unavailable(load_failure.message)

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
            world_state_id=ref.world_id,
            freshness=snapshot.manifest.built_at,
            limitations=_base_limitations(),
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
        world_state_id=ref.world_id,
        freshness=snapshot.manifest.built_at,
        limitations=_base_limitations(),
        query=cleaned,
        hits=deduped[:limit],
        world=ref.to_dict(),
    )


# ---------------------------------------------------------------------------
# ask_as_of — historical questions against the world timeline on disk
# ---------------------------------------------------------------------------


def _parse_as_of_boundary(raw: str) -> tuple[datetime, bool] | None:
    """Interpret `as_of_date` as a UTC instant.

    A bare `YYYY-MM-DD` means "any time on that day" (whole-day inclusive); a
    full ISO-8601 timestamp means exactly that instant. Returns `None` when the
    input is neither — the caller turns that into INVALID_INPUT.
    """
    text = raw.strip()
    if not text:
        return None
    if "T" in text or ":" in text:
        try:
            return parse_timestamp(text, "as_of_date"), False
        except WorldDocumentError:
            return None
    try:
        day = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    return day.replace(tzinfo=UTC), True


def ask_as_of(store: LocalWorldStore, topic: str, as_of_date: str) -> ToolResponse:
    """Answer a topic's truth as it stood at `as_of_date`.

    Reads the world timeline straight off disk (one directory per published
    world) and picks the newest *publishable* world — ACTIVE or SUPERSEDED;
    never BUILDING/CANDIDATE/REJECTED/ROLLED_BACK — whose `built_at` falls on
    or before the asked-for moment, then resolves the topic inside that world.

    UNRESOLVED (`NO_WORLD_AT_DATE`) when no publishable world existed yet at
    that moment: the honest answer to "what did we know on X?" when the answer
    is "nothing had been published".
    """
    cleaned = _clean(topic)
    if not cleaned:
        return ToolResponse.unresolved(ReasonCode.INVALID_INPUT, "topic must be a non-empty string")
    boundary = _parse_as_of_boundary(_clean(as_of_date))
    if boundary is None:
        return ToolResponse.unresolved(
            ReasonCode.INVALID_INPUT,
            "as_of_date must be YYYY-MM-DD or an ISO-8601 timestamp with offset",
        )
    moment_boundary, whole_day = boundary

    if not store.root.is_dir():
        return _unavailable(f"the configured world-state directory does not exist: {store.root}")
    try:
        history = store.list_history()
    except StoreError as exc:
        return _unavailable(str(exc))

    eligible: list[tuple[datetime, str, WorldManifest]] = []
    for manifest in history:
        if manifest.status not in PUBLISHABLE_STATUSES:
            continue
        built = parse_timestamp(manifest.built_at, f"world {manifest.world_id!r} built_at")
        visible = built.date() <= moment_boundary.date() if whole_day else built <= moment_boundary
        if visible:
            eligible.append((built, manifest.world_id, manifest))
    if not eligible:
        readable = ", ".join(f"{m.world_id}[{m.status}@{m.built_at}]" for m in history) or "none"
        return ToolResponse.unresolved(
            ReasonCode.NO_WORLD_AT_DATE,
            f"no publishable world had been built on or before {as_of_date.strip()!r}; "
            f"worlds on disk: {readable}",
            limitations=(
                LIMIT_NO_WORLD,
                LIMIT_READ_ONLY,
                LIMIT_NO_LIVE_SOURCES,
            ),
        )

    manifest = max(eligible, key=lambda entry: (entry[0], entry[1]))[2]
    ref = WorldRef(world_id=manifest.world_id, manifest_hash=manifest.manifest_hash)
    snapshot, load_failure = _load_snapshot(store, ref)
    if snapshot is None or load_failure is not None:
        assert load_failure is not None
        return _unavailable(load_failure.message)

    record, refusal = _resolve_topic(snapshot, cleaned)
    if record is None or refusal is not None:
        assert refusal is not None
        return ToolResponse.unresolved(
            ReasonCode.TOPIC_NOT_FOUND,
            refusal,
            world_state_id=ref.world_id,
            freshness=snapshot.manifest.built_at,
            limitations=(
                *_base_limitations(),
                f"historical answer: served from world {ref.world_id!r} "
                f"(status {manifest.status}, built_at {manifest.built_at})",
            ),
        )

    claims_by_id = {claim.claim_id: claim for claim in snapshot.claims}
    claims = [claims_by_id[cid].to_dict() for cid in record.claim_ids if cid in claims_by_id]
    history_note = (
        f"historical answer: newest publishable world on or before the asked date was "
        f"{ref.world_id!r} (status {manifest.status}, built_at {manifest.built_at})"
    )
    if whole_day:
        history_note += "; a bare date includes everything built during that day"
    if manifest.status == "SUPERSEDED":
        history_note += "; this world has since been superseded"
    return ToolResponse.current(
        f"truth for topic {record.topic_id!r} as of {as_of_date.strip()!r}, "
        f"answered from world {ref.world_id!r}",
        world_state_id=ref.world_id,
        freshness=snapshot.manifest.built_at,
        limitations=(*_base_limitations(), history_note),
        topic=record.to_dict(),
        claims=claims,
        as_of={"as_of_date": as_of_date.strip(), "resolved_from_world": ref.world_id},
        world=ref.to_dict(),
    )


# ---------------------------------------------------------------------------
# get_entity / get_claim / get_change — direct lookups
# ---------------------------------------------------------------------------


def get_entity(store: LocalWorldStore, entity_id: str) -> ToolResponse:
    """Return one resolved entity — by exact id, or uniquely by name/alias.

    UNRESOLVED when the ACTIVE world records no entities at all, or no entity
    matches exactly/uniquely. Entities are only ever what the compiler
    published; a gap in the corpus is a refusal, not a guess.
    """
    cleaned = _clean(entity_id)
    if not cleaned:
        return ToolResponse.unresolved(
            ReasonCode.INVALID_INPUT, "entity_id must be a non-empty string"
        )
    ref, failure = _select_active_world(store)
    if ref is None or failure is not None:
        assert failure is not None
        return _unavailable(failure.message)
    snapshot, load_failure = _load_snapshot(store, ref)
    if snapshot is None or load_failure is not None:
        assert load_failure is not None
        return _unavailable(load_failure.message)

    if not snapshot.entities:
        return ToolResponse.unresolved(
            ReasonCode.ENTITY_NOT_FOUND,
            f"world {ref.world_id!r} records no entities",
            world_state_id=ref.world_id,
            freshness=snapshot.manifest.built_at,
            limitations=_base_limitations(),
        )

    needle = cleaned.casefold()
    exact = [e for e in snapshot.entities if e.entity_id == cleaned]
    soft = [
        e
        for e in snapshot.entities
        if e.entity_id.casefold() == needle
        or e.name.casefold() == needle
        or any(alias.casefold() == needle for alias in e.aliases)
    ]
    candidates = exact or soft
    if not candidates:
        known = sorted(e.entity_id for e in snapshot.entities)
        return ToolResponse.unresolved(
            ReasonCode.ENTITY_NOT_FOUND,
            f"entity {cleaned!r} does not exist in world {ref.world_id!r}; "
            f"known entities: {', '.join(known)}",
            world_state_id=ref.world_id,
            freshness=snapshot.manifest.built_at,
            limitations=_base_limitations(),
        )
    if len(candidates) > 1:
        ids = ", ".join(sorted(e.entity_id for e in candidates))
        return ToolResponse.unresolved(
            ReasonCode.ENTITY_NOT_FOUND,
            f"several entities match {cleaned!r} ({ids}); refusing to choose silently",
            world_state_id=ref.world_id,
            freshness=snapshot.manifest.built_at,
            limitations=_base_limitations(),
        )
    entity = candidates[0]
    claims_by_id = {claim.claim_id: claim for claim in snapshot.claims}
    claims = [claims_by_id[cid].to_dict() for cid in entity.claim_ids if cid in claims_by_id]
    return ToolResponse.current(
        f"entity {entity.entity_id!r} in world {ref.world_id!r}",
        world_state_id=ref.world_id,
        freshness=snapshot.manifest.built_at,
        limitations=(
            *_base_limitations(),
            f"entity matched by {'exact id' if exact else 'name/alias'}",
        ),
        entity=entity.to_dict(),
        claims=claims,
        world=ref.to_dict(),
    )


def get_claim(store: LocalWorldStore, claim_id: str) -> ToolResponse:
    """Return one claim's compiled record (text, status, confidence, evidence)."""
    cleaned = _clean(claim_id)
    if not cleaned:
        return ToolResponse.unresolved(
            ReasonCode.INVALID_INPUT, "claim_id must be a non-empty string"
        )
    ref, failure = _select_active_world(store)
    if ref is None or failure is not None:
        assert failure is not None
        return _unavailable(failure.message)
    snapshot, load_failure = _load_snapshot(store, ref)
    if snapshot is None or load_failure is not None:
        assert load_failure is not None
        return _unavailable(load_failure.message)

    matches = [claim for claim in snapshot.claims if claim.claim_id == cleaned]
    if not matches:
        known = sorted(claim.claim_id for claim in snapshot.claims)
        return ToolResponse.unresolved(
            ReasonCode.CLAIM_NOT_FOUND,
            f"claim {cleaned!r} does not exist in world {ref.world_id!r}; "
            f"known claims: {', '.join(known) or 'none'}",
            world_state_id=ref.world_id,
            freshness=snapshot.manifest.built_at,
            limitations=_base_limitations(),
        )
    claim = matches[0]
    return ToolResponse.current(
        f"claim {claim.claim_id!r} in world {ref.world_id!r}",
        world_state_id=ref.world_id,
        freshness=snapshot.manifest.built_at,
        limitations=_base_limitations(),
        claim=claim.to_dict(),
        world=ref.to_dict(),
    )


def get_change(
    store: LocalWorldStore,
    change_id: str | None = None,
    *,
    source_path: str | None = None,
) -> ToolResponse:
    """Look up one recorded source change by `change_id` or by `source_path`.

    Exactly one selector must be provided. A `source_path` that several changes
    share is refused rather than guessed at: which change is meant is the
    caller's decision, not the tool's.
    """
    cleaned_change = _clean(change_id) if change_id else ""
    cleaned_path = _clean(source_path) if source_path else ""
    if bool(cleaned_change) == bool(cleaned_path):
        return ToolResponse.unresolved(
            ReasonCode.INVALID_INPUT,
            "provide exactly one of change_id or source_path (not both, not neither)",
        )
    ref, failure = _select_active_world(store)
    if ref is None or failure is not None:
        assert failure is not None
        return _unavailable(failure.message)
    snapshot, load_failure = _load_snapshot(store, ref)
    if snapshot is None or load_failure is not None:
        assert load_failure is not None
        return _unavailable(load_failure.message)

    if not snapshot.changes:
        return ToolResponse.unresolved(
            ReasonCode.CHANGE_NOT_FOUND,
            f"world {ref.world_id!r} records no source changes",
            world_state_id=ref.world_id,
            freshness=snapshot.manifest.built_at,
            limitations=_base_limitations(),
        )

    if cleaned_change:
        matches = [c for c in snapshot.changes if c.change_id == cleaned_change]
        if not matches:
            known = sorted(c.change_id for c in snapshot.changes)
            return ToolResponse.unresolved(
                ReasonCode.CHANGE_NOT_FOUND,
                f"change {cleaned_change!r} does not exist in world {ref.world_id!r}; "
                f"known changes: {', '.join(known)}",
                world_state_id=ref.world_id,
                freshness=snapshot.manifest.built_at,
                limitations=_base_limitations(),
            )
    else:
        matches = [c for c in snapshot.changes if c.source_path == cleaned_path]
        if not matches:
            known_paths = sorted({c.source_path for c in snapshot.changes})
            return ToolResponse.unresolved(
                ReasonCode.CHANGE_NOT_FOUND,
                f"no recorded change cites source path {cleaned_path!r} in world "
                f"{ref.world_id!r}; known source paths: {', '.join(known_paths)}",
                world_state_id=ref.world_id,
                freshness=snapshot.manifest.built_at,
                limitations=_base_limitations(),
            )
        if len(matches) > 1:
            ids = ", ".join(sorted(c.change_id for c in matches))
            return ToolResponse.unresolved(
                ReasonCode.CHANGE_NOT_FOUND,
                f"several changes cite source path {cleaned_path!r} ({ids}); "
                "query by change_id instead — refusing to choose silently",
                world_state_id=ref.world_id,
                freshness=snapshot.manifest.built_at,
                limitations=_base_limitations(),
            )

    change = matches[0]
    claims_by_id = {claim.claim_id: claim for claim in snapshot.claims}
    claims = [claims_by_id[cid].to_dict() for cid in change.claim_ids if cid in claims_by_id]
    return ToolResponse.current(
        f"change {change.change_id!r} in world {ref.world_id!r}",
        world_state_id=ref.world_id,
        freshness=snapshot.manifest.built_at,
        limitations=(
            *_base_limitations(),
            "the change ledger covers only sources the compiler recorded in this world",
        ),
        change=change.to_dict(),
        claims=claims,
        world=ref.to_dict(),
    )


# ---------------------------------------------------------------------------
# trace_impact — dependency walk over the world's own edges
# ---------------------------------------------------------------------------


_TRACE_DIRECTIONS = ("downstream", "upstream")


def trace_impact(
    store: LocalWorldStore,
    entity_or_claim_id: str,
    direction: str = "downstream",
    *,
    max_depth: int | None = None,
) -> ToolResponse:
    """What stops being current when this node changes — or where it came from.

    `downstream` walks the blast radius (what goes stale); `upstream` walks the
    provenance (what the node was built from). Both walks run over the
    dependency edges recorded in the ACTIVE world using
    `akc_cir.dependency.DependencyGraph`, so edge semantics (which type carries
    impact and which is inert) have exactly one implementation.

    A node the world knows but no edge references gets an honestly empty answer
    (CURRENT, empty radius, limitation saying why); a node the world does not
    know at all is UNRESOLVED.
    """
    cleaned = _clean(entity_or_claim_id)
    if not cleaned:
        return ToolResponse.unresolved(
            ReasonCode.INVALID_INPUT, "entity_or_claim_id must be a non-empty string"
        )
    cleaned_direction = _clean(direction).casefold()
    if cleaned_direction not in _TRACE_DIRECTIONS:
        return ToolResponse.unresolved(
            ReasonCode.INVALID_INPUT,
            "direction must be one of: " + ", ".join(_TRACE_DIRECTIONS),
        )
    if max_depth is not None and max_depth <= 0:
        return ToolResponse.unresolved(
            ReasonCode.INVALID_INPUT, "max_depth must be a positive integer"
        )
    ref, failure = _select_active_world(store)
    if ref is None or failure is not None:
        assert failure is not None
        return _unavailable(failure.message)
    snapshot, load_failure = _load_snapshot(store, ref)
    if snapshot is None or load_failure is not None:
        assert load_failure is not None
        return _unavailable(load_failure.message)

    known_ids = {
        *(topic.topic_id for topic in snapshot.topics),
        *(claim.claim_id for claim in snapshot.claims),
        *(entity.entity_id for entity in snapshot.entities),
    }
    if cleaned not in known_ids:
        return ToolResponse.unresolved(
            ReasonCode.NODE_NOT_FOUND,
            f"id {cleaned!r} is not a known topic, claim, or entity in world "
            f"{ref.world_id!r}; use search_world to locate nodes first",
            world_state_id=ref.world_id,
            freshness=snapshot.manifest.built_at,
            limitations=_base_limitations(),
        )

    edges = [
        DependencyEdge(source_id=e.source_id, target_id=e.target_id, edge_type=e.edge_type)
        for e in snapshot.dependencies
    ]
    graph = DependencyGraph(edges)
    edge_count = len(edges)
    affected: list[dict[str, Any]]

    if cleaned_direction == "downstream":
        report = graph.impact_of([cleaned], max_depth=max_depth)
        affected = [
            {
                "node_id": path.node_id,
                "depth": path.depth,
                "via": [{"node": node, "edge": edge.value} for node, edge in path.via],
                "path": path.describe(),
            }
            for path in report.affected
        ]
        payload: dict[str, Any] = {
            "seed": cleaned,
            "direction": cleaned_direction,
            "affected": affected,
            "affected_count": len(affected),
            "cycles_detected": [" -> ".join(cycle) for cycle in report.cycles_detected],
            "truncated_at_depth": report.truncated_at_depth,
        }
        message = (
            f"{len(affected)} node(s) stop being current when {cleaned!r} changes"
            if affected
            else f"nothing recorded in world {ref.world_id!r} goes stale when {cleaned!r} changes"
        )
    else:
        provenance = graph.provenance_of(cleaned, max_depth=max_depth)
        affected = [{"node_id": node_id} for node_id in provenance]
        payload = {
            "seed": cleaned,
            "direction": cleaned_direction,
            "provenance": affected,
            "provenance_count": len(provenance),
        }
        message = (
            f"{cleaned!r} was built from {len(provenance)} recorded node(s)"
            if provenance
            else f"no upstream provenance is recorded for {cleaned!r}"
        )

    limitations = list(_base_limitations())
    if edge_count == 0:
        limitations.append(
            "this world records no dependency edges, so every blast radius is "
            "empty by construction — absence of edges is not absence of impact"
        )
    else:
        limitations.append(
            f"blast radius computed from the {edge_count} dependency edge(s) recorded in this world"
        )
    if cleaned not in graph.nodes:
        limitations.append(
            f"no dependency edge references {cleaned!r}; its impact is empty per recorded edges"
        )

    return ToolResponse.current(
        message,
        world_state_id=ref.world_id,
        freshness=snapshot.manifest.built_at,
        limitations=tuple(limitations),
        **payload,
        world=ref.to_dict(),
    )


# ---------------------------------------------------------------------------
# get_world / compare_worlds — the world itself
# ---------------------------------------------------------------------------


def _world_summary_payload(snapshot: WorldSnapshot, ref: WorldRef) -> dict[str, Any]:
    return {
        "manifest": snapshot.manifest.to_dict(),
        "composition": {
            "topics": len(snapshot.topics),
            "claims": len(snapshot.claims),
            "entities": len(snapshot.entities),
            "changes": len(snapshot.changes),
            "dependencies": len(snapshot.dependencies),
        },
        "world": ref.to_dict(),
    }


def get_world(store: LocalWorldStore, world_id: str | None = None) -> ToolResponse:
    """Summarize one world's manifest and composition.

    Without `world_id` the single ACTIVE world is summarized (fail-closed when
    there is not exactly one); with an explicit id any readable world on disk
    answers, including SUPERSEDED ones.
    """
    limitations = _base_limitations()
    if world_id is None:
        ref, failure = _select_active_world(store)
        if ref is None or failure is not None:
            assert failure is not None
            return _unavailable(failure.message)
        snapshot, load_failure = _load_snapshot(store, ref)
        if snapshot is None or load_failure is not None:
            assert load_failure is not None
            return _unavailable(load_failure.message)
        target_desc = f"ACTIVE world {ref.world_id!r}"
    else:
        cleaned = _clean(world_id)
        if not cleaned:
            return ToolResponse.unresolved(
                ReasonCode.INVALID_INPUT, "world_id must be a non-empty string"
            )
        try:
            snapshot = store.load_snapshot(cleaned)
        except UnknownWorldError as exc:
            return ToolResponse.unresolved(
                ReasonCode.WORLD_NOT_FOUND, str(exc), limitations=(LIMIT_NO_WORLD,)
            )
        except WorldDocumentError as exc:
            return _unavailable(str(exc))
        ref = WorldRef(
            world_id=snapshot.manifest.world_id,
            manifest_hash=snapshot.manifest.manifest_hash,
        )
        limitations = (
            *limitations,
            f"explicitly requested world (status {snapshot.manifest.status}); "
            "not necessarily the ACTIVE one",
        )
        target_desc = f"world {ref.world_id!r}"

    payload = _world_summary_payload(snapshot, ref)
    return ToolResponse.current(
        f"summary of {target_desc}",
        world_state_id=ref.world_id,
        freshness=snapshot.manifest.built_at,
        limitations=limitations,
        **payload,
    )


def compare_worlds(store: LocalWorldStore, world_a: str, world_b: str) -> ToolResponse:
    """Diff two worlds' claims: added in B, removed from A, values changed.

    Value changes are reported field by field (text/status/confidence/topics/
    evidence, before → after) so a reviewer sees what moved without opening
    either state file. B is the newer side of the comparison by convention.
    """
    cleaned_a = _clean(world_a)
    cleaned_b = _clean(world_b)
    if not cleaned_a or not cleaned_b:
        return ToolResponse.unresolved(
            ReasonCode.INVALID_INPUT, "world_a and world_b must be non-empty strings"
        )
    try:
        diff = store.diff_worlds(cleaned_a, cleaned_b)
        manifest_a = store.load_manifest(diff.world_a)
        manifest_b = store.load_manifest(diff.world_b)
    except UnknownWorldError as exc:
        return ToolResponse.unresolved(
            ReasonCode.WORLD_NOT_FOUND, str(exc), limitations=(LIMIT_NO_WORLD,)
        )
    except WorldDocumentError as exc:
        return _unavailable(str(exc))

    summary = diff.summary
    message = (
        f"{summary.changed} changed, {summary.added} added, {summary.removed} removed "
        f"claim(s) from {diff.world_a!r} to {diff.world_b!r} "
        f"({summary.unchanged} unchanged)"
    )
    return ToolResponse.current(
        message,
        world_state_id=diff.world_b,
        freshness=manifest_b.built_at,
        limitations=(
            *_base_limitations(),
            f"baseline side {diff.world_a!r} (status {manifest_a.status}, "
            f"built_at {manifest_a.built_at}); comparison target "
            f"{diff.world_b!r} (status {manifest_b.status})",
            "diff covers claims only; topics and entities are not diffed",
        ),
        comparison={
            "world_a": {
                "world_id": manifest_a.world_id,
                "status": manifest_a.status,
                "built_at": manifest_a.built_at,
                "manifest_hash": manifest_a.manifest_hash,
            },
            "world_b": {
                "world_id": manifest_b.world_id,
                "status": manifest_b.status,
                "built_at": manifest_b.built_at,
                "manifest_hash": manifest_b.manifest_hash,
            },
        },
        **diff.to_dict(),
    )
