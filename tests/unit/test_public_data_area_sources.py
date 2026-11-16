"""EIA / FHFA / Census parsers on synthetic fixtures (not recorded, not verified)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path

import pytest
from akc_cir.temporal import TemporalTimeline
from akc_source_adapters.public_data.census import parse_census_bps_csv
from akc_source_adapters.public_data.eia import parse_eia_v2
from akc_source_adapters.public_data.fhfa import parse_fhfa_hpi_csv
from akc_source_adapters.public_data.sources import PUBLIC_SOURCES
from akc_source_adapters.public_data.vintage import comparability_blockers, to_temporal_facts

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "public_data"
URI = "https://example.org/synthetic"
SHA = "sha256:" + "d" * 64


def _eia(raw: bytes | None = None):  # type: ignore[no-untyped-def]
    return parse_eia_v2(
        raw if raw is not None else (FIX / "synthetic_eia_v2.json").read_bytes(),
        URI,
        SHA,
        series_id="SYNTH_EIA",
        units="synthetic",
        frequency="monthly",
        seasonal_adjustment=None,
        rights_id="eia:default",
    )


def _fhfa(raw: bytes | None = None, *, sa: bool = False):  # type: ignore[no-untyped-def]
    return parse_fhfa_hpi_csv(
        raw if raw is not None else (FIX / "synthetic_fhfa_hpi.csv").read_bytes(),
        URI,
        SHA,
        seasonally_adjusted=sa,
        rights_id="fhfa_hpi:default",
    )


def _census(raw: bytes | None = None):  # type: ignore[no-untyped-def]
    return parse_census_bps_csv(
        raw if raw is not None else (FIX / "synthetic_census_bps.csv").read_bytes(),
        URI,
        SHA,
        rights_id="census_bps:default",
    )


def test_eia_fhfa_census_observations_have_no_availability_and_are_held() -> None:
    for obs in (_eia(), _fhfa(), _census()):
        assert obs
        assert all(o.available_on is None and o.available_precision is None for o in obs)
        assert all(o.vintage_id == SHA and o.geography_vintage is None for o in obs)
        facts, held = to_temporal_facts(obs)
        assert facts == ()
        assert len(held) == len(obs)
        assert {h.reason for h in held} <= {"availability_unknown", "missing_value"}
    # a real value is held for unknown availability, never dated
    assert {h.reason for h in to_temporal_facts(_census())[1]} == {"availability_unknown"}


def test_current_mode_serves_them_but_no_known_at_answer_does() -> None:
    obs = _census()
    facts, held = to_temporal_facts(obs, include_unrecorded=True)
    assert held == () and len(facts) == len(obs)
    tl = TemporalTimeline(facts)
    lid = obs[0].logical_id
    assert tl.as_of(logical_id=lid).values == ("120",)
    ans = tl.as_of(known_at=datetime(2030, 1, 1, tzinfo=UTC), logical_id=lid)
    assert ans.values == ()
    assert lid in ans.excluded_unrecorded


def test_fhfa_vs_census_same_cbsa_is_not_comparable() -> None:
    f, c = _fhfa()[0], _census()[0]
    assert f.geography_id == c.geography_id == "90001"
    blockers = comparability_blockers(f, c)
    assert "measure_differs" in blockers
    assert "geography_vintage_unknown" in blockers


def test_two_fhfa_areas_same_definition_differ_only_by_geography_id_are_comparable() -> None:
    obs = _fhfa()
    a = dataclasses.replace(obs[0], geography_vintage="synthetic-2020")
    b = dataclasses.replace(
        next(o for o in obs if o.geography_id == "90002"), geography_vintage="synthetic-2020"
    )
    assert a.geography_id != b.geography_id
    assert comparability_blockers(a, b) == ()
    # the file states no delineation vintage, so as parsed they are not comparable
    assert comparability_blockers(obs[0], obs[2]) == ("geography_vintage_unknown",)


def test_census_source_forbids_parcel_level_approval_claim() -> None:
    assert "parcel_level_approval" in PUBLIC_SOURCES["census_bps"].forbidden_claims
    assert PUBLIC_SOURCES["census_bps"].aggregate_only
    fields = {f.name for f in dataclasses.fields(_census()[0])}
    assert not any("parcel" in n or "approval" in n for n in fields)
    assert "parcel" not in _census()[0].measure


def test_bad_csv_header_raises() -> None:
    with pytest.raises(ValueError, match="header lacks"):
        _fhfa(b"place_id,yr\n1,2020\n")
    with pytest.raises(ValueError, match="header lacks"):
        _census(b"cbsa_code,year\n1,2020\n")
    with pytest.raises(ValueError, match="header lacks"):
        _fhfa(b"hpi_type,hpi_flavor,frequency,level,place_id,yr,period,index_nsa\n", sa=True)


def test_bad_rows_and_payloads_raise_not_skip() -> None:
    with pytest.raises(ValueError, match="bad year/month"):
        _census(b"cbsa_code,year,month,permit_units\n1,2020,13,5\n")
    with pytest.raises(ValueError, match="not JSON"):
        _eia(b"not json")
    with pytest.raises(ValueError, match=r"response.data"):
        _eia(b'{"response": {}}')
    with pytest.raises(ValueError, match="'period'"):
        _eia(b'{"response": {"data": [{"value": "1"}]}}')


def test_non_numeric_value_kept_as_text_or_held() -> None:
    assert any(o.value == "NA" for o in _fhfa())  # never coerced to a number
    assert [o.value for o in _eia()] == ["3.10", "3.25", ""]  # exact text; null -> marker
    _, held = to_temporal_facts(_eia())
    assert [h.reason for h in held].count("missing_value") == 1
