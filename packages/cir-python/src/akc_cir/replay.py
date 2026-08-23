"""Rebuilding the context of a past consumption from immutable history.

Mission §10-§11. A consumption receipt names what an answer saw; this module
makes that name true again. Given a receipt, the directory of per-world
snapshots, and the recorded policy revisions, :func:`reconstruct_context`
reassembles the :class:`ContextPackage` the consumer actually operated on:
the world snapshot as it was, the claims and evidence it contained, and the
policy revision that governed.

The bitemporal rule carries the weight (masterplan §13). A reconstruction is
bounded by what was *known* at ``consumption_time``, not by what is known now.
A policy revision backdated to look older than it is must not reach backwards
over its own recording — the agent that answered earlier was not wrong, it
answered from what was recorded then. So revision selection looks only at
``known_at``; ``valid_from`` is carried but never consulted for selection.
Collapsing the two axes would make it impossible to tell a stale answer from a
dishonest one.

History itself is read-only here. The snapshots are opened, parsed and never
written; a reconstruction leaves every byte of ``world_history_dir``
identical, because a replay that edited its own evidence would be forging the
past it claims to recover.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .consumption_receipt import ConsumptionReceipt

__all__ = [
    "ContextPackage",
    "PolicyRevision",
    "ReplayError",
    "SnapshotClaim",
    "SnapshotEvidence",
    "WorldSnapshot",
    "reconstruct_context",
]


class ReplayError(RuntimeError):
    """The history cannot honestly reconstruct the context being asked for.

    Raised when the named world state has no snapshot, the snapshot lacks
    claims or evidence the receipt names, no policy revision was known at
    consumption time, or the history contradicts itself (knowledge that
    postdates the receipt it is supposed to have fed).
    """


def _require_utc(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime")
    offset = value.utcoffset()
    if offset is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _parse_utc(name: str, value: object) -> datetime:
    if not isinstance(value, str):
        raise ReplayError(f"{name} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReplayError(f"{name} is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReplayError(f"{name} must carry a timezone offset: {value!r}")
    return parsed


@dataclass(frozen=True, slots=True)
class PolicyRevision:
    """One recorded revision of governing policy, on two clocks.

    ``known_at`` is system time: the moment this revision entered the system's
    knowledge. ``valid_from`` is valid time: when the revision declares itself
    to govern from, which may be *earlier* than ``known_at`` — a backdate.
    Selection for a historical context uses ``known_at`` only; a backdated
    declaration cannot vote in a decision that predates its recording.
    """

    revision_id: str
    known_at: datetime
    valid_from: datetime | None = None
    rules: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.revision_id, str) or not self.revision_id.strip():
            raise ValueError("revision_id is required")
        _require_utc("known_at", self.known_at)
        if self.valid_from is not None:
            _require_utc("valid_from", self.valid_from)


@dataclass(frozen=True, slots=True)
class WorldSnapshot:
    """What the history records about one published world state."""

    world_state_id: str
    workspace_id: str
    compiler_version: str
    status: str
    built_at: datetime
    activated_at: datetime


@dataclass(frozen=True, slots=True)
class SnapshotClaim:
    """One claim exactly as the snapshot recorded it, validity windows intact."""

    claim_id: str
    text: str
    valid_from: datetime | None
    valid_until: datetime | None


@dataclass(frozen=True, slots=True)
class SnapshotEvidence:
    """One evidence item as referenced by the snapshot, fields preserved."""

    evidence_id: str
    kind: str
    detail: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ContextPackage:
    """The reconstructed context one consumption operated within.

    Three clocks, each pinned and ordered: ``valid_time`` is when the
    snapshot's facts were compiled to hold (the world's build time),
    ``known_time`` is when everything in this package had entered the system's
    knowledge (world activation, chosen policy recording), and
    ``consumption_time`` is when the answer was served. The invariant
    ``known_time <= consumption_time`` is checked, not assumed — a violation
    means the history contradicts the receipt, and refusing beats fabricating.
    """

    receipt: ConsumptionReceipt
    world_state: WorldSnapshot
    claims: tuple[SnapshotClaim, ...]
    evidence: tuple[SnapshotEvidence, ...]
    policy_rev: PolicyRevision
    valid_time: datetime
    known_time: datetime
    consumption_time: datetime


def _load_snapshot(world_history_dir: Path, world_state_id: str) -> tuple[dict[str, object], Path]:
    path = world_history_dir / f"{world_state_id}.json"
    if not path.is_file():
        raise ReplayError(
            f"world history has no snapshot for {world_state_id} under {world_history_dir}"
        )
    # Read-only, always: a reconstruction may consult history but never edit it.
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ReplayError(f"snapshot {path} is not a JSON object")
    return raw, path


def _parse_snapshot(
    payload: Mapping[str, object], path: Path, expected_world_state_id: str
) -> WorldSnapshot:
    for required in ("world_state_id", "workspace_id", "compiler_version"):
        value = payload.get(required)
        if not isinstance(value, str) or not value:
            raise ReplayError(f"snapshot {path} is missing a usable '{required}'")
    world_state_id = str(payload["world_state_id"])
    if world_state_id != expected_world_state_id:
        raise ReplayError(
            f"snapshot {path} records {world_state_id}, not {expected_world_state_id}"
        )
    return WorldSnapshot(
        world_state_id=world_state_id,
        workspace_id=str(payload["workspace_id"]),
        compiler_version=str(payload["compiler_version"]),
        status=str(payload.get("status", "ACTIVE")),
        built_at=_parse_utc("built_at", payload.get("built_at")),
        activated_at=_parse_utc("activated_at", payload.get("activated_at")),
    )


def _parse_claims(
    payload: Mapping[str, object], path: Path, wanted: tuple[str, ...]
) -> tuple[SnapshotClaim, ...]:
    raw_claims = payload.get("claims", [])
    if not isinstance(raw_claims, list):
        raise ReplayError(f"snapshot {path} has a malformed 'claims' list")
    by_id: dict[str, SnapshotClaim] = {}
    for entry in raw_claims:
        if not isinstance(entry, dict):
            raise ReplayError(f"snapshot {path} has a non-object claim entry")
        claim_id = entry.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id:
            raise ReplayError(f"snapshot {path} has a claim without a usable 'claim_id'")
        valid_from = (
            _parse_utc(f"claim {claim_id} valid_from", entry["valid_from"])
            if entry.get("valid_from") is not None
            else None
        )
        valid_until = (
            _parse_utc(f"claim {claim_id} valid_until", entry["valid_until"])
            if entry.get("valid_until") is not None
            else None
        )
        by_id[claim_id] = SnapshotClaim(
            claim_id=claim_id,
            text=str(entry.get("text", "")),
            valid_from=valid_from,
            valid_until=valid_until,
        )
    missing = sorted(set(wanted) - set(by_id))
    if missing:
        raise ReplayError(
            f"snapshot {path} does not contain claim(s) the receipt names: {', '.join(missing)}"
        )
    return tuple(by_id[claim_id] for claim_id in wanted)


def _parse_evidence(
    payload: Mapping[str, object], path: Path, wanted: tuple[str, ...]
) -> tuple[SnapshotEvidence, ...]:
    raw_evidence = payload.get("evidence", [])
    if not isinstance(raw_evidence, list):
        raise ReplayError(f"snapshot {path} has a malformed 'evidence' list")
    by_id: dict[str, SnapshotEvidence] = {}
    for entry in raw_evidence:
        if not isinstance(entry, dict):
            raise ReplayError(f"snapshot {path} has a non-object evidence entry")
        evidence_id = entry.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise ReplayError(f"snapshot {path} has evidence without a usable 'evidence_id'")
        by_id[evidence_id] = SnapshotEvidence(
            evidence_id=evidence_id,
            kind=str(entry.get("kind", "")),
            detail=dict(entry),
        )
    missing = sorted(set(wanted) - set(by_id))
    if missing:
        raise ReplayError(
            f"snapshot {path} does not contain evidence the receipt names: {', '.join(missing)}"
        )
    return tuple(by_id[evidence_id] for evidence_id in wanted)


def _select_policy(
    revisions: Sequence[PolicyRevision], consumption_time: datetime
) -> PolicyRevision | None:
    """The latest revision *known* at consumption time, ties broken stably."""
    known_then = [
        revision for revision in revisions if revision.known_at <= consumption_time
    ]
    if not known_then:
        return None
    return max(known_then, key=lambda revision: (revision.known_at, revision.revision_id))


def reconstruct_context(
    receipt: ConsumptionReceipt,
    world_history_dir: str | Path,
    policy_revisions: Sequence[PolicyRevision],
) -> ContextPackage:
    """Rebuild the context a past consumption saw, from immutable history.

    Loads the snapshot named by the receipt's ``world_state_id`` from
    ``world_history_dir``, selects the claims and evidence the receipt names
    out of it exactly as recorded, and chooses the policy revision that was
    known at ``requested_at`` — never a later-recorded one, however far back
    it declares its validity. Raises :class:`ReplayError` rather than guessing
    whenever the history cannot honestly answer.
    """
    directory = Path(world_history_dir)
    payload, path = _load_snapshot(directory, receipt.world_state_id)
    snapshot = _parse_snapshot(payload, path, receipt.world_state_id)
    claims = _parse_claims(payload, path, receipt.claim_ids)
    evidence = _parse_evidence(payload, path, receipt.evidence_ids)

    policy_rev = _select_policy(policy_revisions, receipt.requested_at)
    if policy_rev is None:
        raise ReplayError(
            f"no policy revision was known at {receipt.requested_at.isoformat()}; "
            "the earliest recorded one postdates this consumption"
        )

    known_time = max(snapshot.activated_at, policy_rev.known_at)
    if known_time > receipt.requested_at:
        raise ReplayError(
            f"inconsistent history: parts of this context were only known at "
            f"{known_time.isoformat()}, after the receipt was served at "
            f"{receipt.requested_at.isoformat()}"
        )

    return ContextPackage(
        receipt=receipt,
        world_state=snapshot,
        claims=claims,
        evidence=evidence,
        policy_rev=policy_rev,
        valid_time=snapshot.built_at,
        known_time=known_time,
        consumption_time=receipt.requested_at,
    )
