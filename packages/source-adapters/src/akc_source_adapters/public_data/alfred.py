"""ALFRED (vintage) observations -> VintageObservation. Offline parser only.

Endpoint, parameter and field names are second-hand (repository notes cite only
the FRED/ALFRED doc pages) and UNVERIFIED until WO-D21-5 records real responses.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date
from typing import Any

from .vintage import VintageObservation

OPEN_ENDED = "9999-12-31"


def build_alfred_request_url(series_id: str) -> str:
    """Request URL for every vintage of a series, without any key.

    UNVERIFIED: host, path and parameter names are from memory of the FRED API
    docs (series observations, realtime period), not from a verified
    primary-source read. Replace after WO-D21-5.
    """
    if not series_id.strip():
        raise ValueError("series_id must be non-empty")
    query = urllib.parse.urlencode(
        {
            "series_id": series_id,
            "realtime_start": "1776-07-04",
            "realtime_end": OPEN_ENDED,
            "file_type": "json",
        }
    )
    return f"https://api.stlouisfed.org/fred/series/observations?{query}"


def _text(row: dict[str, Any], name: str) -> str:
    v = row.get(name)
    # An empty `value` is a missing-value marker the timeline holds, not an error.
    if not isinstance(v, str) or (not v and name != "value"):
        raise ValueError(f"ALFRED row: missing or non-text field {name!r}")
    return v


def _day(row: dict[str, Any], name: str) -> date:
    try:
        return date.fromisoformat(_text(row, name))
    except ValueError as exc:
        raise ValueError(f"ALFRED row: field {name!r} is not an ISO date") from exc


def parse_alfred_observations(
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
    """Rows (realtime_start, realtime_end, date, value) -> one vintage each.

    `available_on = realtime_start` (day precision); `superseded_on =
    realtime_end` unless it is the open-ended sentinel; `vintage_id =
    realtime_start`. `measure` is the series id. A malformed row raises.
    `rights_id` is required beyond the work order's signature: the observation
    record carries it.
    """
    try:
        doc = json.loads(raw, parse_float=str, parse_int=str)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"ALFRED payload is not JSON: {exc}") from exc
    rows = doc.get("observations") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise ValueError("ALFRED payload: field 'observations' must be a list")
    out: list[VintageObservation] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("ALFRED row: not an object")
        start = _day(row, "realtime_start")
        end_text = _text(row, "realtime_end")
        out.append(
            VintageObservation(
                source_id="alfred",
                series_id=series_id,
                period_start=_day(row, "date"),
                period_end=None,
                value=_text(row, "value"),
                unit=units,
                frequency=frequency,
                seasonal_adjustment=seasonal_adjustment,
                measure=series_id,
                geography_id=None,
                geography_level=None,
                geography_vintage=None,
                vintage_id=start.isoformat(),
                available_on=start,
                available_precision="day",
                superseded_on=None if end_text == OPEN_ENDED else _day(row, "realtime_end"),
                source_uri=source_uri,
                raw_sha256=raw_sha256,
                rights_id=rights_id,
            )
        )
    return tuple(out)
