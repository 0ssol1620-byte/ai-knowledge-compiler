"""Census Building Permits Survey -> VintageObservation. Offline parsers only.

`parse_census_bps_cbsa_ascii` reads the publisher's CBSA current-month file
(`CBSA<YYMM>C.TXT`) in the record layout of the Census "CBSA ASCII
Documentation" (01/22/2024), checked in WO-D21-5 against a recording of
`cbsa2609c.txt`. The recording is a shape check only (WO-D21-6, D21-L3): no
reuse sentence was found for the `www2` files, so its rights stay unknown.

A value is an aggregated count of authorized housing units for an area and
month; it is never a parcel-level or individual legal approval
(`parcel_level_approval` is a forbidden claim of this source). `available_on`
is never set; `geography_vintage` is set only if the file states one.
"""

from __future__ import annotations

import csv
import io
import re
import urllib.parse
from datetime import date

from .vintage import VintageObservation

MEASURE = "housing_units_authorized_by_permit_count"

# Record layout fields 7, 10, 13, 16 ("Estimates With Imputation" units), keyed by
# the structure-type label the file's first header line puts above each Units column.
_CBSA_UNIT_COLUMNS = {6: "1-unit", 9: "2-units", 12: "3-4 units", 15: "5+ units"}
_CBSA_FIELDS = 29
_CBSA_FILE = re.compile(r"cbsa(\d{4})c\.txt", re.IGNORECASE)


def parse_census_bps_cbsa_ascii(
    raw: bytes,
    source_uri: str,
    raw_sha256: str,
    *,
    rights_id: str,
) -> tuple[VintageObservation, ...]:
    """One observation per CBSA and structure type: units with imputation, exact text.

    Only a current-month file is accepted (year-to-date and annual files sum other
    periods), named by `source_uri`, and every row must carry that file's month.
    The file's text encoding is not documented; it is read byte-for-byte as
    latin-1 and only ASCII digit fields become values (the area name, the only
    field seen with non-ASCII bytes, is not stored). Reported-only, buildings and
    valuation columns are not emitted. Any layout difference raises.
    """
    name = urllib.parse.unquote(urllib.parse.urlsplit(source_uri).path.rsplit("/", 1)[-1])
    match = _CBSA_FILE.fullmatch(name)
    if match is None:
        raise ValueError(f"Census BPS: {name!r} is not a CBSA current-month file (CBSA<YYMM>C.TXT)")
    yymm = match.group(1)
    rows = list(csv.reader(io.StringIO(raw.decode("latin-1"))))
    if (
        len(rows) < 2
        or [rows[0][i].strip() if i < len(rows[0]) else "" for i in _CBSA_UNIT_COLUMNS]
        != list(_CBSA_UNIT_COLUMNS.values())
        or [c.strip() for c in rows[1][5:8]] != ["Bldgs", "Units", "Value"]
        or any(
            (rows[1][i].strip() if i < len(rows[1]) else "") != "Units" for i in _CBSA_UNIT_COLUMNS
        )
    ):
        raise ValueError("Census BPS: header lines differ from the CBSA ASCII record layout")
    out: list[VintageObservation] = []
    seen: dict[str, list[str]] = {}
    for row in rows[2:]:
        if len(row) <= 1 and not "".join(row).strip():
            continue  # a blank line (the layout has one after the headers); separators are data
        if len(row) != _CBSA_FIELDS:
            raise ValueError(f"Census BPS row: {len(row)} fields, layout has {_CBSA_FIELDS}")
        survey, cbsa = row[0].strip(), row[2].strip()
        # ponytail: century fixed at 20; the layout dates files from 2024, revisit in 2100
        if not (
            len(survey) == 6 and survey.isdigit() and survey.startswith("20") and survey[2:] == yymm
        ):
            raise ValueError(f"Census BPS row: survey date {survey!r} is not this file's month")
        if not 1 <= int(survey[4:]) <= 12:
            raise ValueError(f"Census BPS row: survey date {survey!r} has no valid month")
        if not (len(cbsa) == 5 and cbsa.isdigit()):
            raise ValueError(f"Census BPS row: CBSA code {cbsa!r} is not five digits")
        if cbsa in seen:
            if seen[cbsa] != row:
                raise ValueError(f"Census BPS rows conflict for {cbsa} {survey}")
            continue
        seen[cbsa] = row
        start = date(int(survey[:4]), int(survey[4:]), 1)
        for col, label in _CBSA_UNIT_COLUMNS.items():
            value = row[col]
            if not (value.isascii() and value.isdigit()):
                raise ValueError(f"Census BPS row {cbsa} {survey}: units {value!r} is not a count")
            out.append(
                VintageObservation(
                    source_id="census_bps",
                    series_id=f"{MEASURE}:{label}:{cbsa}",
                    period_start=start,
                    period_end=None,
                    value=value,
                    unit="housing_units",
                    frequency="monthly",
                    seasonal_adjustment=None,  # not stated by the file or its layout
                    measure=f"{MEASURE}:{label}",
                    geography_id=cbsa,
                    geography_level="CBSA",
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
    if not out:
        raise ValueError("Census BPS: the file has no data rows")
    return tuple(out)
