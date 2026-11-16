"""Census Building Permits Survey CSV -> VintageObservation. Offline parser only.

Columns (cbsa_code, year, month, permit_units, optional delineation_vintage)
are second-hand and UNVERIFIED until WO-D21-5. The value is an aggregated
count of authorized housing units for an area and month; it is never a
parcel-level or individual legal approval (`parcel_level_approval` is a
forbidden claim of this source). `available_on` is never set;
`geography_vintage` is set only if the file states a delineation vintage.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from .vintage import VintageObservation

REQUIRED = ("cbsa_code", "year", "month", "permit_units")
MEASURE = "housing_units_authorized_by_permit_count"


def parse_census_bps_csv(
    raw: bytes,
    source_uri: str,
    raw_sha256: str,
    *,
    rights_id: str,
) -> tuple[VintageObservation, ...]:
    """One monthly area count per row, value as exact text; bad header/rows raise."""
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        fields = reader.fieldnames or ()
    except UnicodeDecodeError as exc:
        raise ValueError(f"Census payload is not UTF-8: {exc}") from exc
    missing = [c for c in REQUIRED if c not in fields]
    if missing:
        raise ValueError(f"Census header lacks columns {missing}")
    out: list[VintageObservation] = []
    for row in reader:
        if None in row.values():
            raise ValueError(f"Census row: ragged row: {row}")
        cbsa = row["cbsa_code"].strip()
        if not cbsa:
            raise ValueError("Census row: empty cbsa_code")
        try:
            start = date(int(row["year"]), int(row["month"]), 1)
        except ValueError as exc:
            raise ValueError(
                f"Census row: bad year/month {row['year']!r}/{row['month']!r}"
            ) from exc
        out.append(
            VintageObservation(
                source_id="census_bps",
                series_id=f"{MEASURE}:{cbsa}",
                period_start=start,
                period_end=None,
                value=row["permit_units"],
                unit="count",
                frequency="monthly",
                seasonal_adjustment="NSA",
                measure=MEASURE,
                geography_id=cbsa,
                geography_level="CBSA",
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
