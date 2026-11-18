"""FHFA House Price Index CSV -> VintageObservation. Offline parser only.

Column names (hpi_type, hpi_flavor, frequency, level, place_name, place_id,
yr, period, index_nsa, index_sa) are those of FHFA's master file
(`hpi_master.csv`) as FHFA's `hpi_dictionary.xlsx` lists them, and match the
first 64 KiB of that file recorded in WO-D21-5 (the whole file was over the
size cap). The recorded file also has `rstderr` and `note` columns, and the
dictionary lists a `Median Price ($)` the file does not have; none is read.
An index of an area is an aggregate: it is never a property valuation.
`available_on` is never set (no release time in the file); `geography_vintage`
is set only if an optional `delineation_vintage` column states one.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any

from .vintage import VintageObservation

REQUIRED = ("hpi_type", "hpi_flavor", "frequency", "level", "place_id", "yr", "period")
_MONTHS_PER_PERIOD = {"quarterly": 3, "monthly": 1}


def parse_fhfa_hpi_csv(
    raw: bytes,
    source_uri: str,
    raw_sha256: str,
    *,
    seasonally_adjusted: bool,
    rights_id: str,
) -> tuple[VintageObservation, ...]:
    """One observation per row from `index_sa` or `index_nsa`; bad header/rows raise."""
    value_col = "index_sa" if seasonally_adjusted else "index_nsa"
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        fields = reader.fieldnames or ()
    except UnicodeDecodeError as exc:
        raise ValueError(f"FHFA payload is not UTF-8: {exc}") from exc
    missing = [c for c in (*REQUIRED, value_col) if c not in fields]
    if missing:
        raise ValueError(f"FHFA header lacks columns {missing}")
    out: list[VintageObservation] = []
    seen: dict[tuple[str, date], dict[str | None, Any]] = {}
    for row in reader:
        freq = (row["frequency"] or "").strip().lower()
        if freq not in _MONTHS_PER_PERIOD or None in row.values():
            raise ValueError(f"FHFA row: unsupported frequency or ragged row: {row}")
        try:
            start = date(int(row["yr"]), (int(row["period"]) - 1) * _MONTHS_PER_PERIOD[freq] + 1, 1)
        except ValueError as exc:
            raise ValueError(f"FHFA row: bad yr/period {row['yr']!r}/{row['period']!r}") from exc
        place = row["place_id"].strip()
        if not place:
            raise ValueError("FHFA row: empty place_id")
        flavor = f"{row['hpi_type'].strip()}:{row['hpi_flavor'].strip()}"
        sid = f"{flavor}:{freq}:{place}:{value_col}"
        # only a byte-identical row is a duplicate; any other difference contradicts the file
        if (sid, start) in seen:
            if seen[(sid, start)] != row:
                raise ValueError(f"FHFA rows conflict for {sid} {start}")
            continue
        seen[(sid, start)] = row
        out.append(
            VintageObservation(
                source_id="fhfa_hpi",
                series_id=sid,
                period_start=start,
                period_end=None,
                value=row[value_col],  # exact text; non-numeric stays text
                unit="index",
                frequency=freq,
                seasonal_adjustment="SA" if seasonally_adjusted else "NSA",
                measure=f"hpi:{flavor}",
                geography_id=place,
                geography_level=row["level"].strip() or None,
                geography_vintage=(row.get("delineation_vintage") or "").strip() or None,
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
