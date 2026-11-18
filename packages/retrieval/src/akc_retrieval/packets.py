"""Public, score-free evidence packet: what was admitted, under which cut, and what was not.

Internal ranking features (scores) never enter these types; public and internal
DTOs are separate. Timestamps are read from row metadata and never inferred.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict

from .engine import ProviderAttestationError
from .models import EvidenceHit, RetrievalQuery, VerificationState
from .temporal import TemporalAdmission, _moment, admit


class _Public(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EvidenceItem(_Public):
    stable_id: str
    evidence_block_ids: tuple[uuid.UUID, ...]
    source_hash: str
    source_locator: str | None
    valid_from: AwareDatetime | None
    valid_to: AwareDatetime | None
    recorded_at: AwareDatetime | None
    available_at: AwareDatetime | None
    verification_state: VerificationState | None


class PacketCoverage(_Public):
    admitted: int
    excluded_unrecorded: int = 0
    excluded_known_after: int = 0
    excluded_unknown_validity: int = 0
    excluded_not_valid: int = 0
    excluded_unavailable: int = 0
    excluded_available_after: int = 0


class EvidencePacket(_Public):
    world_id: str
    snapshot_id: str
    valid_at: AwareDatetime | None
    known_at: AwareDatetime | None
    available_at: AwareDatetime | None
    access_epoch: int
    expires_at: AwareDatetime
    items: tuple[EvidenceItem, ...]
    coverage: PacketCoverage


def _locator(metadata: dict[str, object]) -> str | None:
    keys = ("document_id", "source_type")
    parts = [str(metadata[k]) for k in keys if metadata.get(k) is not None]
    return "/".join(parts) or None


def _item(hit: EvidenceHit) -> EvidenceItem:
    m = hit.metadata
    state = m.get("verification_state")
    return EvidenceItem(
        stable_id=hit.stable_id,
        evidence_block_ids=hit.evidence_block_ids,
        source_hash=hit.source_hash,
        source_locator=_locator(m),
        valid_from=_moment(m, "valid_from"),
        valid_to=_moment(m, "valid_to"),
        recorded_at=_moment(m, "recorded_at"),
        available_at=_moment(m, "available_at"),
        verification_state=None if state is None else VerificationState(state),
    )


def build_evidence_packet(
    hits: Sequence[EvidenceHit],
    admissions: Sequence[TemporalAdmission],
    *,
    world_id: str,
    snapshot_id: str,
    query: RetrievalQuery,
    access_epoch: int,
    expires_at: datetime,
    now: datetime | None = None,
) -> EvidencePacket:
    """`admissions` covers every candidate considered; `hits` are exactly the admitted ones."""
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ValueError("expires_at must be timezone-aware")
    if expires_at <= (now or datetime.now(UTC)):
        raise ValueError("packet would already be expired")
    if any(a.admitted != (a.reason == "admitted") for a in admissions):
        raise ProviderAttestationError("inconsistent temporal admission")
    if any(not admit(h.metadata, query).admitted for h in hits):
        raise ProviderAttestationError("packet item outside the temporal cut")
    counts = Counter(a.reason for a in admissions)
    if counts["admitted"] != len(hits):
        raise ValueError("admitted count does not match the hits supplied")
    return EvidencePacket(
        world_id=world_id,
        snapshot_id=snapshot_id,
        valid_at=query.valid_at,
        known_at=query.known_at,
        available_at=query.available_at,
        access_epoch=access_epoch,
        expires_at=expires_at,
        items=tuple(_item(h) for h in hits),
        coverage=PacketCoverage(
            admitted=counts.pop("admitted", 0),
            **dict(counts),
        ),
    )
