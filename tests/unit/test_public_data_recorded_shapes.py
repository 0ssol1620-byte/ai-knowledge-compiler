"""WO-D21-5: shapes read from the publishers' own pages and recordings, and the reviewed rights.

Every data row below is synthetic (invented area codes and counts). Only the
Census header lines are the publisher's layout text. The recordings themselves
are not committed (see tests/fixtures/public_data/recorded_manifest.json).
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from pathlib import Path

import pytest
from akc_source_adapters.public_data.census import parse_census_bps_cbsa_ascii
from akc_source_adapters.public_data.eia import parse_eia_v2
from akc_source_adapters.public_data.rights import ACTIONS, permits, require
from akc_source_adapters.public_data.sources import PUBLIC_SOURCES, REVIEWED_RIGHTS
from akc_source_adapters.public_data.vintage import VintageObservation

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests" / "fixtures" / "public_data" / "recorded_manifest.json"
SHA = "sha256:" + "0" * 64
CENSUS_URI = "https://www2.census.gov/econ/bps/CBSA%20(beginning%20Jan%202024)/cbsa2609c.txt"

# The two header lines of the Census CBSA ASCII file, as the publisher writes them.
CENSUS_HEADER = (
    "Survey,CSA,CBSA,HHEADER,CBSA,,1-unit,,,2-units,,,3-4 units,,,5+ units,,,"
    "1-unit rep,,,2-units rep,,,3-4 units rep,,,5+ units rep\r\n"
    "Date,Code,Code,,Name,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,"
    "Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,      Bldgs,Units,Value,"
    "Bldgs,Units,Value\r\n \r\n"
)


def _census_row(survey: str, cbsa: str, name: bytes = b"Synthetic Metro  ZZ ") -> bytes:
    counts = "1,2,300,0,0,0,0,0,0,1,7,900,1,2,300,0,0,0,0,0,0,1,7,900"
    return f"{survey},999,{cbsa},4,".encode() + name + f",{counts}\r\n".encode()


def _census(body: bytes, uri: str = CENSUS_URI) -> tuple[VintageObservation, ...]:
    return parse_census_bps_cbsa_ascii(
        CENSUS_HEADER.encode() + body, uri, SHA, rights_id="census_bps:default"
    )


def test_census_publisher_layout_is_not_the_assumed_csv() -> None:
    # The retired WO-D21-4 parser assumed a header (cbsa_code, year, month, permit_units)
    # that the publisher's file does not have; the layout parser refuses that shape.
    with pytest.raises(ValueError, match="header lines differ"):
        parse_census_bps_cbsa_ascii(
            b"cbsa_code,cbsa_name,year,month,permit_units\n90001,Synthetic,2026,9,120\n",
            CENSUS_URI,
            SHA,
            rights_id="census_bps:default",
        )


def test_census_cbsa_file_gives_units_per_structure_type_with_no_assumed_adjustment() -> None:
    obs = _census(_census_row("202609", "90001") + _census_row("202609", "90002"))
    assert len(obs) == 8
    first = [o for o in obs if o.geography_id == "90001"]
    assert [(o.measure.rsplit(":", 1)[1], o.value) for o in first] == [
        ("1-unit", "2"),
        ("2-units", "0"),
        ("3-4 units", "0"),
        ("5+ units", "7"),
    ]
    o = first[0]
    assert (o.period_start.isoformat(), o.frequency, o.geography_level) == (
        "2026-09-01",
        "monthly",
        "CBSA",
    )
    assert o.seasonal_adjustment is None and o.geography_vintage is None
    assert o.available_on is None and "parcel" not in o.measure


def test_census_non_ascii_area_name_does_not_break_parsing() -> None:
    # The recorded file carries a latin-1 byte (0xF1) in an area name.
    obs = _census(_census_row("202609", "90003", name=b"Espa\xf1ola  ZZ "))
    assert {o.value for o in obs} == {"2", "0", "7"}


@pytest.mark.parametrize(
    ("body", "uri", "message"),
    [
        (_census_row("202609", "90001"), CENSUS_URI.replace("2609c", "2609y"), "current-month"),
        (_census_row("202608", "90001"), CENSUS_URI, "not this file's month"),
        (_census_row("202609", "9001"), CENSUS_URI, "five digits"),
        (
            _census_row("202609", "90001").replace(b",7,900", b",x,900", 1),
            CENSUS_URI,
            "not a count",
        ),
        (_census_row("202609", "90001")[:-6] + b"\r\n", CENSUS_URI, "fields"),
    ],
)
def test_census_file_that_differs_from_the_layout_raises(
    body: bytes, uri: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _census(body, uri)


def test_census_changed_header_raises() -> None:
    raw = CENSUS_HEADER.replace("5+ units,", "5 units,", 1).encode() + _census_row(
        "202609", "90001"
    )
    with pytest.raises(ValueError, match="header lines differ"):
        parse_census_bps_cbsa_ascii(raw, CENSUS_URI, SHA, rights_id="census_bps:default")


def _eia(rows: list[dict[str, object]], **kw: str) -> tuple[VintageObservation, ...]:
    raw = json.dumps({"response": {"data": rows}}).encode()
    return parse_eia_v2(
        raw,
        "https://api.eia.gov/v2/x/data",
        SHA,
        series_id="synthetic",
        units="cents per kilowatthour",
        frequency="annual",
        seasonal_adjustment=None,
        rights_id="eia:default",
        **kw,
    )


def test_eia_value_column_is_named_by_the_data_parameter() -> None:
    # EIA's documentation shows /data rows with the requested column, e.g. `price`.
    rows: list[dict[str, object]] = [
        {"period": "2010", "price": "7.28", "price-units": "cents per kilowatthour"}
    ]
    assert [o.value for o in _eia(rows, value_column="price")] == ["7.28"]


def test_eia_row_without_the_value_column_raises_instead_of_reading_as_missing() -> None:
    # Before WO-D21-5 an absent `value` became the missing-value marker, silently.
    with pytest.raises(ValueError, match="no field 'value'"):
        _eia([{"period": "2010", "price": "7.28"}])


def test_recorded_manifest_carries_no_key_and_matches_any_cached_bytes() -> None:
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    text = MANIFEST.read_text(encoding="utf-8")
    assert "api_key" not in text.lower()
    assert {r["source_id"] for r in doc["not_recorded"]} == {"alfred", "eia"}
    assert len(doc["recordings"]) == 3
    for r in doc["recordings"]:
        parts = urllib.parse.urlsplit(r["url"])
        assert parts.scheme == "https" and not parts.query and not parts.fragment
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", r["sha256"]) and r["bytes"] > 0
        assert "/" not in r["file"] and "\\" not in r["file"]
        cached = ROOT / doc["cache_dir"] / r["file"]
        if cached.exists():  # the cache is untracked; where it exists it must be these bytes
            raw = cached.read_bytes()
            assert ("sha256:" + hashlib.sha256(raw).hexdigest(), len(raw)) == (
                r["sha256"],
                r["bytes"],
            )


def test_reviewed_rights_never_allow_redistribute_or_resell() -> None:
    assert {r.source_id for r in REVIEWED_RIGHTS} == set(PUBLIC_SOURCES)
    for r in REVIEWED_RIGHTS:
        assert r.verified and r.expires_on is not None
        assert "not a legal review" in (r.reviewer or "")
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", r.terms_snapshot_sha256 or "")
        assert (r.terms_url or "").startswith("https://")
        assert r.permissions["redistribute"] != "allow"
        assert r.permissions["resell"] != "allow"


def test_alfred_reviewed_record_denies_every_action() -> None:
    (alfred,) = [r for r in REVIEWED_RIGHTS if r.source_id == "alfred"]
    today = alfred.verified_on
    assert today is not None
    for action in ACTIONS:
        assert alfred.permissions[action] == "deny"
        assert not permits(alfred, action, today=today)


def test_reviewed_allows_are_exactly_the_quoted_ones_and_expire() -> None:
    allowed = {
        r.source_id: {a for a in ACTIONS if r.permissions[a] == "allow"} for r in REVIEWED_RIGHTS
    }
    output = {"quote", "display", "export"}
    processing = {"ingest", "model_processing", "derive"}
    assert allowed == {
        "sec_edgar": processing | output,
        "eia": processing,
        "fhfa_hpi": processing,
        "alfred": set(),
        "census_bps": set(),
    }
    sec = PUBLIC_SOURCES["sec_edgar"]
    today = REVIEWED_RIGHTS[0].verified_on
    assert today is not None
    record = require(sec, None, "ingest", REVIEWED_RIGHTS, today=today)
    assert record.source_id == "sec_edgar"
    assert record.expires_on is not None
    assert not permits(
        record, "ingest", today=record.expires_on.replace(year=record.expires_on.year + 1)
    )


def test_manifest_marks_the_shape_check_and_the_over_cap_recording() -> None:
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_source = {r["source_id"]: r for r in doc["recordings"]}
    assert by_source["census_bps"]["purpose"] == "shape_check_only"  # D21-L3
    assert by_source["sec_edgar"]["over_cap_decoded"] is True  # D21-L4, 2 MB decoded cap
    assert by_source["sec_edgar"]["decoded_bytes"] > 2 * 1024 * 1024
    assert "over_cap_decoded" not in by_source["census_bps"]
