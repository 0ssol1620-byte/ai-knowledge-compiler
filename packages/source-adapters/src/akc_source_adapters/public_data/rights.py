"""Fail-closed rights gate for public-data sources.

Unknown is deny. A permission counts only when the record is verified (terms
URL, terms snapshot hash, verification date, reviewer) and not expired.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .sources import PublicSource

ACTIONS = (
    "ingest",
    "model_processing",
    "derive",
    "quote",
    "display",
    "export",
    "redistribute",
    "resell",
)
# Actions a source-level record can never license for a per-series source.
SERIES_ONLY_ACTIONS = ("quote", "display", "export", "redistribute", "resell")

Permission = Literal["allow", "deny", "unknown"]


class RightsDenied(ValueError):
    def __init__(self, rights_id: str, action: str, reason: str) -> None:
        super().__init__(f"{rights_id}: {action} denied ({reason})")
        self.rights_id = rights_id
        self.action = action
        self.reason = reason


@dataclass(frozen=True)
class RightsRecord:
    rights_id: str
    source_id: str
    series_id: str | None
    terms_url: str | None
    terms_snapshot_sha256: str | None
    verified_on: date | None
    reviewer: str | None
    expires_on: date | None
    attribution: str | None
    permissions: Mapping[str, Permission]

    def __post_init__(self) -> None:
        bad = sorted(set(self.permissions) - set(ACTIONS))
        if bad:
            raise ValueError(f"unknown rights action(s): {bad}")

    @property
    def verified(self) -> bool:
        return all((self.terms_url, self.terms_snapshot_sha256, self.verified_on, self.reviewer))


def _denial(record: RightsRecord, action: str, today: date) -> str | None:
    """Reason the action is not permitted, or None when it is."""
    if action not in ACTIONS:
        raise ValueError(f"unknown rights action: {action}")
    permission = record.permissions.get(action, "unknown")
    if permission == "deny":
        return "denied"
    if permission != "allow":
        return "unknown"
    if not record.verified:
        return "unverified"
    if record.expires_on is not None and record.expires_on < today:
        return "expired"
    return None


def permits(record: RightsRecord, action: str, *, today: date) -> bool:
    return _denial(record, action, today) is None


def rights_for(
    source: PublicSource, series_id: str | None, register: Iterable[RightsRecord]
) -> RightsRecord | None:
    """Series-level record if present, else the source-level record, else None."""
    records = [r for r in register if r.source_id == source.source_id]
    if series_id is not None:
        for r in records:
            if r.series_id == series_id:
                return r
    for r in records:
        if r.series_id is None:
            return r
    return None


def require(
    source: PublicSource,
    series_id: str | None,
    action: str,
    register: Iterable[RightsRecord],
    *,
    today: date,
) -> RightsRecord:
    record = rights_for(source, series_id, register)
    if record is None:
        raise RightsDenied(f"{source.source_id}:{series_id}", action, "unknown")
    reason = _denial(record, action, today)
    if (
        reason is None
        and source.per_series_rights
        and record.series_id is None
        and action in SERIES_ONLY_ACTIONS
    ):
        reason = "series_record_required"
    if reason is not None:
        raise RightsDenied(record.rights_id, action, reason)
    return record
