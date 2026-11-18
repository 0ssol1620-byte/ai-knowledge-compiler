"""Temporal cut for retrieval: valid_at / known_at / available_at.

Reuses `akc_cir.temporal` for the valid and known axes. Availability (when the
source was published to the reader) is a third axis the timeline does not model;
it is never inferred from another timestamp. No cut set = current mode.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from akc_cir.temporal import TemporalFact, TemporalPolicy, TemporalSource, TemporalTimeline
from pydantic import BaseModel, ConfigDict

from .models import RetrievalQuery

Reason = Literal[
    "admitted",
    "excluded_unrecorded",
    "excluded_known_after",
    "excluded_unknown_validity",
    "excluded_not_valid",
    "excluded_unavailable",
    "excluded_available_after",
]


class TemporalAdmission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    admitted: bool
    reason: Reason


def _moment(metadata: Mapping[str, object], key: str) -> datetime | None:
    value = metadata.get(key)
    if value is None:
        return None
    try:
        if not isinstance(value, str):
            raise ValueError("not a string")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("naive timestamp")
    except ValueError as error:
        # Lazy import: engine imports this module.
        from .engine import ProviderAttestationError

        raise ProviderAttestationError(
            f"temporal metadata {key!r} is not an ISO-8601 timestamp with offset"
        ) from error
    return parsed


def admit(metadata: Mapping[str, object], query: RetrievalQuery) -> TemporalAdmission:
    def no(reason: Reason) -> TemporalAdmission:
        return TemporalAdmission(admitted=False, reason=reason)

    if query.known_at is not None or query.valid_at is not None:
        valid_from = _moment(metadata, "valid_from") if query.valid_at else None
        valid_to = _moment(metadata, "valid_to") if query.valid_at else None
        fact = TemporalFact(
            logical_id="row",
            value="row",
            valid_from=valid_from,
            valid_to=valid_to,
            recorded_at=_moment(metadata, "recorded_at") if query.known_at else None,
            temporal_source=(
                TemporalSource.EXPLICIT
                if valid_from is not None or valid_to is not None
                else TemporalSource.UNKNOWN
            ),
        )
        timeline = TemporalTimeline([fact])
        if query.known_at is not None:
            known = timeline.as_of(known_at=query.known_at)
            if not known.facts:
                return no(
                    "excluded_unrecorded" if known.excluded_unrecorded else "excluded_known_after"
                )
        if query.valid_at is not None:
            valid = timeline.as_of(
                valid_at=query.valid_at,
                policy=(
                    TemporalPolicy.INCLUDE_UNKNOWN
                    if query.include_unknown_validity
                    else TemporalPolicy.EXCLUDE_UNKNOWN
                ),
            )
            if not valid.facts:
                return no(
                    "excluded_unknown_validity" if valid.excluded_unknown else "excluded_not_valid"
                )
    if query.available_at is not None:
        available = _moment(metadata, "available_at")
        if available is None:
            return no("excluded_unavailable")
        if available > query.available_at:
            return no("excluded_available_after")
    return TemporalAdmission(admitted=True, reason="admitted")
