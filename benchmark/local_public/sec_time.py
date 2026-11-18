"""Two-witness SEC acceptance time (LPC design 2.6). Always timezone-aware UTC, or None.

W1 = FSDS `sub.accepted` (Eastern, minute-rounded); W2 = bulk submissions.zip `acceptanceDateTime`
(UTC in most filings, Eastern digits mislabelled `Z` in some). Single-witness or disagreeing
filings give None; nothing is estimated.
"""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
_TOL = timedelta(seconds=30)


def _digits(value: str) -> datetime | None:
    """Naive datetime from the wall-clock digits; the zone label (`Z`, offset) is ignored."""
    try:
        return datetime.fromisoformat(value.strip().removesuffix("Z").split("+")[0]).replace(
            tzinfo=None
        )
    except ValueError:
        return None


def accepted_at(w1_fsds: str, w2_bulk: str | None) -> datetime | None:
    w1_naive = _digits(w1_fsds) if isinstance(w1_fsds, str) else None
    w2_naive = _digits(w2_bulk) if isinstance(w2_bulk, str) else None
    if w1_naive is None or w2_naive is None:
        return None
    w1 = w1_naive.replace(tzinfo=_ET).astimezone(UTC)
    as_utc = w2_naive.replace(tzinfo=UTC)
    if abs(as_utc - w1) <= _TOL:
        return as_utc
    as_eastern = w2_naive.replace(tzinfo=_ET).astimezone(UTC)
    if abs(as_eastern - w1) <= _TOL:
        return as_eastern
    return None


def bulk_index(zip_file: zipfile.ZipFile) -> dict[str, str]:
    """adsh -> raw `acceptanceDateTime` over every submissions JSON in the bulk zip."""
    out: dict[str, str] = {}
    for name in zip_file.namelist():
        if not name.endswith(".json"):
            continue
        doc = json.loads(zip_file.read(name))
        block = doc.get("filings", {}).get("recent", doc) if isinstance(doc, dict) else {}
        accessions = block.get("accessionNumber") or []
        stamps = block.get("acceptanceDateTime") or []
        for adsh, stamp in zip(accessions, stamps, strict=False):
            if isinstance(adsh, str) and isinstance(stamp, str) and stamp:
                out[adsh] = stamp
    return out
