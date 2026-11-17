"""EIA / FHFA / Census parsers on synthetic fixtures (not recorded, not verified)."""

from __future__ import annotations

import dataclasses
import itertools
from datetime import UTC, datetime
from pathlib import Path

import pytest
from akc_cir.temporal import TemporalTimeline
from akc_source_adapters.public_data.census import parse_census_bps_cbsa_ascii
from akc_source_adapters.public_data.eia import parse_eia_v2
from akc_source_adapters.public_data.fhfa import parse_fhfa_hpi_csv
from akc_source_adapters.public_data.sources import PUBLIC_SOURCES
from akc_source_adapters.public_data.vintage import comparability_blockers, to_temporal_facts

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "public_data"
URI = "https://example.org/synthetic"
CENSUS_URI = "https://example.org/synthetic/cbsa2601c.txt"
# Synthetic file in the publisher's CBSA ASCII layout (publisher's two header lines, invented rows).
CENSUS_FILE = (FIX / "synthetic_cbsa2601c.txt").read_bytes()
CENSUS_HEAD = b"".join(CENSUS_FILE.splitlines(keepends=True)[:3])


def _crow(cbsa: str, units: str = "5", survey: str = "202601", extra: str = "") -> bytes:
    counts = "0,0,0,0,0,0,1,7,900,1,2,300,0,0,0,0,0,0,1,7,900"
    return f"{survey},999,{cbsa},4,Synthetic{extra},1,{units},300,{counts}\r\n".encode()


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
    return parse_census_bps_cbsa_ascii(
        raw if raw is not None else CENSUS_FILE,
        CENSUS_URI,
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
    with pytest.raises(ValueError, match="header lines differ"):
        _census(b"cbsa_code,year\n1,2020\n")
    with pytest.raises(ValueError, match="header lacks"):
        _fhfa(b"hpi_type,hpi_flavor,frequency,level,place_id,yr,period,index_nsa\n", sa=True)


def test_bad_rows_and_payloads_raise_not_skip() -> None:
    with pytest.raises(ValueError, match="no valid month"):
        parse_census_bps_cbsa_ascii(
            CENSUS_HEAD + _crow("90001", survey="202613"),
            CENSUS_URI.replace("2601", "2613"),
            SHA,
            rights_id="census_bps:default",
        )
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


def test_same_period_rows_with_different_values_raise() -> None:
    with pytest.raises(ValueError, match="conflict"):
        _eia(
            b'{"response": {"data": [{"period": "2020-01", "value": "1"},'
            b' {"period": "2020", "value": "2"}]}}'
        )
    with pytest.raises(ValueError, match="conflict"):
        _fhfa(
            b"hpi_type,hpi_flavor,frequency,level,place_id,yr,period,index_nsa,index_sa\n"
            b"t,f,quarterly,MSA,1,2020,1,100,100\nt,f,quarterly,MSA,1,2020,1,200,200\n"
        )
    with pytest.raises(ValueError, match="conflict"):
        _census(CENSUS_HEAD + _crow("90001", "5") + _crow("90001", "9"))
    # one identical duplicate row is one area: four structure-type observations, not eight
    assert len(_census(CENSUS_HEAD + _crow("90001") + _crow("90001"))) == 4


def test_same_value_rows_that_differ_in_any_other_field_raise() -> None:
    # a same-value duplicate must not silently drop a contradicting geography field
    with pytest.raises(ValueError, match="conflict"):
        _census(CENSUS_HEAD + _crow("90001", extra="2013") + _crow("90001", extra="2023"))
    with pytest.raises(ValueError, match="conflict"):
        _fhfa(
            b"hpi_type,hpi_flavor,frequency,level,place_id,yr,period,index_nsa,index_sa\n"
            b"t,f,quarterly,MSA,1,2020,1,100,1\nt,f,quarterly,State,1,2020,1,100,1\n"
        )
    with pytest.raises(ValueError, match="conflict"):
        _eia(
            b'{"response": {"data": [{"period": "2020-01", "stateid": "CA", "value": "1"},'
            b' {"period": "2020-01", "stateid": "TX", "value": "1"}]}}'
        )


def _assert_no_row_dropped(parse, raws: list[tuple[bytes, int]]) -> None:  # type: ignore[no-untyped-def]
    """Each (payload, distinct row count): ValueError, or one observation per distinct row."""
    for raw, distinct in raws:
        try:
            out = parse(raw)
        except ValueError:
            continue
        assert len(out) == distinct, raw
        assert len({o.logical_id for o in out}) == len(out), raw


def _csv_pairs(header: str, cells: tuple[tuple[str, ...], ...]) -> list[tuple[bytes, int]]:
    rows = [",".join(r) for r in itertools.product(*cells)]
    return [
        (f"{header}\n{a}\n{b}\n".encode(), len({a, b}))
        for a, b in itertools.product(rows, repeat=2)
    ]


def test_csv_parsers_never_drop_a_non_identical_row_property() -> None:
    census_rows = [
        _crow(c, u, extra=e)
        for c, u, e in itertools.product(("90001", "90002"), ("5", "9"), ("", "x"))
    ]
    _assert_no_row_dropped(
        _census,
        [
            (CENSUS_HEAD + a + b, len({a, b}) * 4)  # four structure types per distinct row
            for a, b in itertools.product(census_rows, repeat=2)
        ],
    )
    fhfa = _csv_pairs(
        "hpi_type,hpi_flavor,frequency,level,place_id,yr,period,index_nsa,index_sa,"
        "delineation_vintage",
        (
            ("t",),
            ("f",),
            ("quarterly", "monthly"),
            ("MSA", "State"),
            ("1",),
            ("2020",),
            ("1", "01"),
            ("100", "200"),
            ("100", "101"),
            ("", "2013"),
        ),
    )
    _assert_no_row_dropped(lambda raw: _fhfa(raw, sa=False), fhfa)
    _assert_no_row_dropped(lambda raw: _fhfa(raw, sa=True), fhfa)


def test_eia_parser_never_drops_a_non_identical_row_property() -> None:
    rows = [
        f'{{"period": "{p}", "value": {v}{f}}}'
        for p, v, f in itertools.product(
            ("2020", "2020-01", "2020-01-01"),
            ("1", "1.0", "null", '"2"'),
            ("", ', "stateid": "CA"', ', "stateid": "TX"'),
        )
    ]
    _assert_no_row_dropped(
        _eia,
        [
            (f'{{"response": {{"data": [{a}, {b}]}}}}'.encode(), len({a, b}))
            for a, b in itertools.product(rows, repeat=2)
        ],
    )


def test_census_century_must_be_the_files_not_the_last_two_digits() -> None:
    with pytest.raises(ValueError, match="not this file's month"):
        _census(CENSUS_HEAD + _crow("90001", survey="192601"))


def test_census_file_without_data_rows_raises() -> None:
    with pytest.raises(ValueError, match="no data rows"):
        _census(CENSUS_HEAD)


def test_census_row_of_only_separators_raises_not_skipped() -> None:
    with pytest.raises(ValueError, match="fields"):
        _census(CENSUS_HEAD + b",,,,\r\n")
    with pytest.raises(ValueError, match="not this file's month"):
        _census(CENSUS_HEAD + b"," * 28 + b"\r\n")


def test_census_units_label_is_checked_at_every_units_column() -> None:
    old = b"Units,Value,Bldgs,Units,Value,Bldgs,Units"
    changed = CENSUS_HEAD.replace(old, b"Units,Value,Bldgs,Cost,Value,Bldgs,Units", 1)
    assert changed != CENSUS_HEAD
    with pytest.raises(ValueError, match="header lines differ"):
        _census(changed + _crow("90001"))
