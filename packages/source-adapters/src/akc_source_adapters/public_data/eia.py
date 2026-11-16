"""EIA open-data v2 response -> VintageObservation. Offline parser only.

Response shape (`response.data[]` rows with `period` and `value`) is
second-hand and UNVERIFIED until WO-D21-5 records a real response. The
response itself is the only vintage evidence: `available_on` is never set (the
source gives no per-row release time), so every observation is held by
`to_temporal_facts` and answers no `known_at` question.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from .vintage import VintageObservation


def _period(text: str) -> date:
    try:
        parts = [int(p) for p in text.split("-")]
        if len(parts) not in (1, 2, 3):
            raise ValueError(text)
        return date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
    except ValueError as exc:
        raise ValueError(f"EIA row: field 'period' is not YYYY[-MM[-DD]]: {text!r}") from exc


def parse_eia_v2(
    raw: bytes,
    source_uri: str,
    raw_sha256: str,
    *,
    series_id: str,
    units: str,
    frequency: str | None,
    seasonal_adjustment: str | None,
    rights_id: str,
) -> tuple[VintageObservation, ...]:
    """One observation per row; value kept as exact source text; malformed rows raise."""
    try:
        doc = json.loads(raw, parse_float=str, parse_int=str)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"EIA payload is not JSON: {exc}") from exc
    resp = doc.get("response") if isinstance(doc, dict) else None
    rows = resp.get("data") if isinstance(resp, dict) else None
    if not isinstance(rows, list):
        raise ValueError("EIA payload: field 'response.data' must be a list")
    out: list[VintageObservation] = []
    seen: dict[date, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("EIA row: not an object")
        period: Any = row.get("period")
        value: Any = row.get("value")
        if not isinstance(period, str) or not period:
            raise ValueError("EIA row: missing or non-text field 'period'")
        if value is None:
            value = ""  # a null value is a missing marker the timeline holds
        elif not isinstance(value, str):
            raise ValueError("EIA row: field 'value' must be text, number or null")
        start = _period(period)
        if start in seen:
            if seen[start] != value:
                raise ValueError(
                    f"EIA rows conflict for {series_id} {start}: {seen[start]!r} vs {value!r}"
                )
            continue
        seen[start] = value
        out.append(
            VintageObservation(
                source_id="eia",
                series_id=series_id,
                period_start=start,
                period_end=None,
                value=value,
                unit=units,
                frequency=frequency,
                seasonal_adjustment=seasonal_adjustment,
                measure=series_id,
                geography_id=None,
                geography_level=None,
                geography_vintage=None,
                vintage_id=raw_sha256,
                available_on=None,
                available_precision=None,
                superseded_on=None,
                source_uri=source_uri,
                raw_sha256=raw_sha256,
                rights_id=rights_id,
            )
        )
    return tuple(out)
