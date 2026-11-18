"""ALFRED / EDGAR offline parsers on synthetic fixtures (not recorded, not verified)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from akc_cir.temporal import TemporalTimeline
from akc_source_adapters.public_data.alfred import (
    build_alfred_request_url,
    parse_alfred_observations,
)
from akc_source_adapters.public_data.edgar import parse_edgar_companyfacts
from akc_source_adapters.public_data.vintage import to_temporal_facts

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "public_data"
ALFRED = (FIXTURES / "synthetic_alfred_observations.json").read_bytes()
EDGAR = (FIXTURES / "synthetic_edgar_companyfacts.json").read_bytes()
URI = "https://example.org/synthetic"
SHA = "sha256:" + "c" * 64


def _alfred(raw: bytes = ALFRED):  # type: ignore[no-untyped-def]
    return parse_alfred_observations(
        raw,
        URI,
        SHA,
        series_id="SYNTH1",
        units="index",
        frequency="monthly",
        seasonal_adjustment="NSA",
        rights_id="alfred:SYNTH1",
    )


def _edgar(raw: bytes = EDGAR):  # type: ignore[no-untyped-def]
    return parse_edgar_companyfacts(raw, URI, SHA, rights_id="sec_edgar:default")


def test_alfred_rows_become_vintages_with_day_availability() -> None:
    obs = _alfred()
    assert len(obs) == 4
    first = next(o for o in obs if o.vintage_id == "2020-01-15")
    assert first.available_on == date(2020, 1, 15)
    assert first.available_precision == "day"
    assert first.superseded_on == date(2021, 2, 9)
    assert first.period_start == date(2019, 12, 1)
    assert first.value == "100.10"  # exact source text
    assert first.logical_id == "alfred:SYNTH1:2019-12-01"
    assert first.raw_sha256 == SHA and first.source_uri == URI


def test_alfred_open_ended_vintage_has_no_superseded_on() -> None:
    latest = next(o for o in _alfred() if o.vintage_id == "2021-02-10")
    assert latest.superseded_on is None


def test_alfred_parse_then_timeline_answers_a_backdated_revision_correctly() -> None:
    facts, held = to_temporal_facts(_alfred())
    assert [h.reason for h in held] == ["missing_value"]  # the "." row
    timeline = TemporalTimeline(facts)
    lid = "alfred:SYNTH1:2019-12-01"
    assert timeline.as_of(known_at=datetime(2019, 12, 31, tzinfo=UTC), logical_id=lid).values == ()
    assert timeline.as_of(known_at=datetime(2020, 6, 1, tzinfo=UTC), logical_id=lid).values == (
        "100.10",
    )
    assert timeline.as_of(known_at=datetime(2021, 6, 1, tzinfo=UTC), logical_id=lid).values == (
        "101.50",
    )


def test_alfred_request_url_has_no_key_and_is_https() -> None:
    url = build_alfred_request_url("SYNTH1")
    assert url.startswith("https://") and "series_id=SYNTH1" in url and "key" not in url
    with pytest.raises(ValueError):
        build_alfred_request_url(" ")


def test_edgar_amendment_is_a_later_vintage_not_an_overwrite() -> None:
    obs = _edgar()
    rev = [o for o in obs if ":Revenues:USD" in o.series_id]
    assert [(o.vintage_id, o.value) for o in rev] == [
        ("0001234567-20-000001", "1000"),  # identical repeat collapsed
        ("0001234567-20-000009", "1010"),
    ]
    assert rev[0].series_id == "1234567:us-gaap:Revenues:USD:2019-12-31"
    assert rev[0].available_on == date(2020, 2, 14)
    facts, held = to_temporal_facts(obs)
    assert held == ()
    tl = TemporalTimeline(facts)
    lid = rev[0].logical_id
    assert tl.as_of(known_at=datetime(2020, 3, 1, tzinfo=UTC), logical_id=lid).values == ("1000",)
    assert tl.as_of(known_at=datetime(2020, 7, 1, tzinfo=UTC), logical_id=lid).values == ("1010",)


def _edgar_doc(*rows: dict) -> bytes:  # type: ignore[type-arg]
    return json.dumps(
        {"cik": 1, "facts": {"us-gaap": {"Revenues": {"units": {"USD": list(rows)}}}}}
    ).encode()


def test_edgar_periods_sharing_a_start_date_are_not_revisions_of_each_other() -> None:
    # Real filings: Q1 -> 6M YTD -> FY all start on the same day. Different end = different fact.
    q1 = {
        "start": "2019-01-01",
        "end": "2019-03-31",
        "val": 100,
        "accn": "A1",
        "filed": "2019-05-01",
    }
    h1 = {
        "start": "2019-01-01",
        "end": "2019-06-30",
        "val": 250,
        "accn": "A2",
        "filed": "2019-08-01",
    }
    obs = _edgar(_edgar_doc(q1, h1))
    facts, held = to_temporal_facts(obs)
    assert held == ()
    assert len({o.logical_id for o in obs}) == 2
    assert all(f.superseded_at is None for f in facts)
    tl = TemporalTimeline(facts)
    known = datetime(2019, 9, 1, tzinfo=UTC)
    by_end = {o.period_end: o.logical_id for o in obs}
    assert tl.as_of(known_at=known, logical_id=by_end[date(2019, 3, 31)]).values == ("100",)
    assert tl.as_of(known_at=known, logical_id=by_end[date(2019, 6, 30)]).values == ("250",)


def test_edgar_empty_or_non_text_start_raises_not_becomes_instant() -> None:
    row = {"end": "2019-03-31", "val": 1, "accn": "A1", "filed": "2019-05-01"}
    for bad in ("", 5, None):
        with pytest.raises(ValueError, match="start"):
            _edgar(_edgar_doc({**row, "start": bad}))


def test_edgar_instant_fact_uses_end_as_start_and_keeps_text() -> None:
    (assets,) = [o for o in _edgar() if o.series_id.endswith(":Assets:USD")]
    assert assets.period_start == assets.period_end == date(2019, 12, 31)
    assert assets.value == "5000.50"


def test_edgar_conflicting_values_in_one_accession_are_held() -> None:
    doc = json.loads(EDGAR)
    rows = doc["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    rows.append({**rows[0], "val": 999})  # same accession, other value
    obs = _edgar(json.dumps(doc).encode())
    facts, held = to_temporal_facts(obs)
    assert {h.reason for h in held} == {"ambiguous_vintage"}
    assert len(held) == 3  # 1000, 999 and the 10-K/A of the same logical id
    assert not [f for f in facts if "Revenues" in f.logical_id]
    assert [f for f in facts if "Assets" in f.logical_id]  # other concepts unaffected


@pytest.mark.parametrize("missing", ["filed", "accn", "val", "end"])
def test_malformed_payload_raises_not_skips(missing: str) -> None:
    doc = json.loads(EDGAR)
    del doc["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0][missing]
    with pytest.raises(ValueError, match=missing):
        _edgar(json.dumps(doc).encode())


def test_malformed_alfred_and_structure_raise() -> None:
    with pytest.raises(ValueError, match="realtime_start"):
        _alfred(b'{"observations":[{"realtime_end":"9999-12-31","date":"2020-01-01","value":"1"}]}')
    with pytest.raises(ValueError, match="'date'"):
        _alfred(
            b'{"observations":[{"realtime_start":"2020-01-01","realtime_end":"9999-12-31",'
            b'"date":"not-a-date","value":"1"}]}'
        )
    with pytest.raises(ValueError, match="observations"):
        _alfred(b"[]")
    with pytest.raises(ValueError, match="not JSON"):
        _alfred(b"{")
    with pytest.raises(ValueError, match="facts"):
        _edgar(b'{"cik": 1}')
    bad_date = {
        "cik": 1,
        "facts": {
            "t": {
                "c": {
                    "units": {
                        "USD": [{"end": "2020-01-01", "val": 1, "accn": "a", "filed": "2020-13-45"}]
                    }
                }
            }
        },
    }
    with pytest.raises(ValueError, match="filed"):
        _edgar(json.dumps(bad_date).encode())
