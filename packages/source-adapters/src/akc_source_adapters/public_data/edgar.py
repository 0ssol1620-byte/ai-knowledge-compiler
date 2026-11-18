"""EDGAR XBRL companyfacts -> VintageObservation. Offline parser only.

Field names (`cik`, `facts`, `units`, `start`, `end`, `val`, `accn`, `filed`)
match a WO-D21-5 recording of `data.sec.gov/api/xbrl/companyfacts` (one filer);
SEC's API page names the endpoint but documents no field. Fields the parser does
not read (`fy`, `fp`, `form`, `frame`) are present in that recording.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from .vintage import VintageObservation


def _need(fact: dict[str, Any], name: str, where: str) -> str:
    v = fact.get(name)
    if not isinstance(v, str) or not v:
        raise ValueError(f"EDGAR fact {where}: missing or non-text field {name!r}")
    return v


def _day(text: str, name: str, where: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"EDGAR fact {where}: field {name!r} is not an ISO date") from exc


def _obj(v: object, where: str) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ValueError(f"EDGAR payload: {where} must be an object")
    return v


def parse_edgar_companyfacts(
    raw: bytes, source_uri: str, raw_sha256: str, *, rights_id: str
) -> tuple[VintageObservation, ...]:
    """One observation per (taxonomy, concept, unit, fact).

    `series_id = cik:taxonomy:concept:unit`, plus `:end` when the fact has a
    `start` (a duration; same-start facts with different ends are different
    periods, not revisions); `vintage_id = accn`, `available_on
    = filed`. Identical repeats within the payload collapse; the same accession
    with a different value is kept twice so `to_temporal_facts` holds it as
    `ambiguous_vintage`. A malformed fact raises. `rights_id` is required beyond
    the work order's signature: the observation record carries it.
    """
    try:
        doc = json.loads(raw, parse_float=str, parse_int=str)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"EDGAR payload is not JSON: {exc}") from exc
    doc = _obj(doc, "document")
    cik = _need(doc, "cik", "document")
    out: dict[tuple[str, ...], VintageObservation] = {}
    for taxonomy, concepts in _obj(doc.get("facts"), "facts").items():
        for concept, body in _obj(concepts, f"facts.{taxonomy}").items():
            units = _obj(_obj(body, concept).get("units"), f"{concept}.units")
            for unit, rows in units.items():
                base = f"{cik}:{taxonomy}:{concept}:{unit}"
                if not isinstance(rows, list):
                    raise ValueError(f"EDGAR payload: {base} must be a list")
                for fact in rows:
                    fact = _obj(fact, base)
                    end = _need(fact, "end", base)
                    # A duration fact is its own series per end date: Q1, 6M YTD, 9M YTD and FY
                    # share a start, and only a same-period refiling is a revision.
                    start = _need(fact, "start", base) if "start" in fact else None
                    series_id = base if start is None else f"{base}:{end}"
                    accn = _need(fact, "accn", series_id)
                    filed = _need(fact, "filed", series_id)
                    val = _need(fact, "val", series_id)
                    o = VintageObservation(
                        source_id="sec_edgar",
                        series_id=series_id,
                        period_start=_day(start or end, "start", series_id),
                        period_end=_day(end, "end", series_id),
                        value=val,
                        unit=unit,
                        frequency=None,
                        seasonal_adjustment=None,
                        measure=f"{taxonomy}:{concept}",
                        geography_id=None,
                        geography_level=None,
                        geography_vintage=None,
                        vintage_id=accn,
                        available_on=_day(filed, "filed", series_id),
                        available_precision="day",
                        superseded_on=None,
                        source_uri=source_uri,
                        raw_sha256=raw_sha256,
                        rights_id=rights_id,
                    )
                    out.setdefault((o.logical_id, accn, val, end, filed), o)
    return tuple(out[k] for k in sorted(out))
