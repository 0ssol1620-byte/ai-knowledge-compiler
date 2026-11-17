"""EIA open-data v2 response -> VintageObservation. Offline parser only.

`response.data[]` rows with `period` are as EIA's API documentation shows
(snapshot read in WO-D21-5). That page names a row's value column after the
`data[]` request parameter (e.g. `price`, with `price-units`), so the column is
an argument; the default `value` is not shown on that page and stays
unverified. No EIA response was recorded (no key was provided). The
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
    value_column: str = "value",
) -> tuple[VintageObservation, ...]:
    """One observation per row; value kept as exact source text; malformed rows raise.

    A row without `value_column` raises: an absent column is a request/shape
    mismatch, not a missing value. Only an explicit null is a missing marker.
    """
    try:
        doc = json.loads(raw, parse_float=str, parse_int=str)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"EIA payload is not JSON: {exc}") from exc
    resp = doc.get("response") if isinstance(doc, dict) else None
    rows = resp.get("data") if isinstance(resp, dict) else None
    if not isinstance(rows, list):
        raise ValueError("EIA payload: field 'response.data' must be a list")
    out: list[VintageObservation] = []
    seen: dict[date, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("EIA row: not an object")
        period: Any = row.get("period")
        if not isinstance(period, str) or not period:
            raise ValueError("EIA row: missing or non-text field 'period'")
        if value_column not in row:
            raise ValueError(f"EIA row: no field {value_column!r}")
        value: Any = row[value_column]
        if value is None:
            value = ""  # a null value is a missing marker the timeline holds
        elif not isinstance(value, str):
            raise ValueError(f"EIA row: field {value_column!r} must be text, number or null")
        start = _period(period)
        # only an identical row is a duplicate; any other field (period text, facet) contradicts
        if start in seen:
            if seen[start] != row:
                raise ValueError(
                    f"EIA rows conflict for {series_id} {start}: {seen[start]!r} vs {row!r}"
                )
            continue
        seen[start] = row
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
