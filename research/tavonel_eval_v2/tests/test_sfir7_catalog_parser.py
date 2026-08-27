"""Hostile tests for the Libraries.io Repositories reader.

The parser stands between an external 24.9 GB deposit and SFIR7's frame rule, and
almost everything that can go wrong there goes wrong *quietly*: a shifted column
produces a roster of real repositories ranked by the wrong number, and a silently
skipped row turns a corpus of millions into a smaller corpus with nobody
noticing. So these controls are written for silence, not for crashes.

Each one names the wrong roster it prevents.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir7_catalog_parser as parser  # noqa: E402

HEADER = [
    "ID",
    "Host Type",
    "Name with Owner",
    "Description",
    "Fork",
    "Created Timestamp",
    "Updated Timestamp",
    "Last pushed Timestamp",
    "Homepage URL",
    "Size",
    "Stars Count",
    "Language",
    "UUID",
    "SourceRank",
    "License",
    "Status",
]


def _row(**overrides: str) -> list[str]:
    values = {
        "ID": "1001",
        "Host Type": "GitHub",
        "Name with Owner": "pypa/setuptools",
        "Description": "a, comma, laden, description",
        "Fork": "false",
        "Created Timestamp": "2010-03-01 00:00:00 UTC",
        "Updated Timestamp": "2019-12-01 00:00:00 UTC",
        "Last pushed Timestamp": "2019-12-30 00:00:00 UTC",
        "Homepage URL": "",
        "Size": "12345",
        "Stars Count": "900",
        "Language": "Python",
        "UUID": "24038237",
        "SourceRank": "27",
        "License": "MIT",
        "Status": "",
    }
    values.update(overrides)
    return [values[column] for column in HEADER]


def _write(tmp_path: Path, rows: list[list[str]], header: list[str] | None = None) -> Path:
    import csv

    path = tmp_path / "repositories.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header if header is not None else HEADER)
        writer.writerows(rows)
    return path


# --- the happy path, so the refusals below mean something --------------------


def test_a_well_formed_row_carries_the_catalogues_own_values(tmp_path: Path):
    records, proof = parser.read_catalog(_write(tmp_path, [_row()]))
    assert len(records) == 1
    record = records[0]
    assert record.record_id == "1001"
    assert record.host_uuid == "24038237"
    assert record.name_with_owner == "pypa/setuptools"
    assert record.catalog_rank_value == 27
    assert record.spdx_license_id == "MIT"
    assert record.fork is False
    assert proof["rows_total"] == 1
    assert proof["rows_rejected"] == 0
    assert proof["rank_recomputed_by_tavonel"] is False


def test_a_description_full_of_commas_does_not_shift_a_column(tmp_path: Path):
    """Quoted commas are exactly how a naive split produces a plausible, wrong roster."""
    records, _ = parser.read_catalog(
        _write(tmp_path, [_row(Description='he said, "hello", and left, twice')])
    )
    assert records[0].catalog_rank_value == 27
    assert records[0].spdx_license_id == "MIT"


# --- the header is a contract ------------------------------------------------


def test_a_missing_declared_column_is_refused_by_name(tmp_path: Path):
    """The failure this exists for: SourceRank disappears, and a positional
    parser reads License as the rank. Every repository still looks real."""
    header = [c for c in HEADER if c != "SourceRank"]
    path = _write(tmp_path, [], header=header)
    with pytest.raises(parser.CatalogParseRefused, match="SourceRank"):
        parser.read_catalog(path)


def test_a_reordered_header_is_read_correctly_not_positionally(tmp_path: Path):
    """A parser that survives reordering is a parser that is not counting columns."""
    header = list(reversed(HEADER))
    values = dict(zip(HEADER, _row(), strict=True))
    path = _write(tmp_path, [[values[c] for c in header]], header=header)
    records, _ = parser.read_catalog(path)
    assert records[0].catalog_rank_value == 27
    assert records[0].name_with_owner == "pypa/setuptools"


def test_a_duplicated_declared_column_is_refused(tmp_path: Path):
    """Two columns named SourceRank: which one is the rank is not a guess."""
    header = [*HEADER, "SourceRank"]
    path = _write(tmp_path, [[*_row(), "999"]], header=header)
    with pytest.raises(parser.CatalogParseRefused, match="repeats a column"):
        parser.read_catalog(path)


def test_a_utf8_bom_on_the_first_column_does_not_break_the_contract(tmp_path: Path):
    header = ["﻿ID", *HEADER[1:]]
    path = _write(tmp_path, [_row()], header=header)
    records, _ = parser.read_catalog(path)
    assert records[0].record_id == "1001"


def test_an_empty_file_is_refused(tmp_path: Path):
    path = tmp_path / "repositories.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(parser.CatalogParseRefused, match="empty"):
        parser.read_catalog(path)


# --- a row that cannot be read is counted, never guessed ---------------------


def test_a_non_integer_rank_is_rejected_and_counted_not_coerced(tmp_path: Path):
    """Coercing to 0 would rank a repository last while looking like data."""
    path = _write(tmp_path, [_row(SourceRank="not-a-number"), _row(ID="2")])
    records, proof = parser.read_catalog(path)
    assert len(records) == 1
    assert proof["rejection_reasons"] == {"RANK_NOT_AN_INTEGER": 1}
    assert proof["rows_total"] == 2


def test_a_blank_rank_is_rejected_rather_than_treated_as_zero(tmp_path: Path):
    _, proof = parser.read_catalog(_write(tmp_path, [_row(SourceRank="")]))
    assert proof["rejection_reasons"] == {"NO_PUBLISHED_RANK": 1}


def test_a_short_row_is_rejected_not_padded(tmp_path: Path):
    """A truncated line padded with empties yields a record whose rank is
    whatever happened to be in range. Refuse it."""
    path = tmp_path / "repositories.csv"
    path.write_text(",".join(HEADER) + "\n1001,GitHub,pypa/setuptools\n", encoding="utf-8")
    records, proof = parser.read_catalog(path)
    assert records == []
    assert proof["rejection_reasons"] == {"SHORT_ROW": 1}


def test_a_name_that_is_not_owner_slash_repo_is_rejected(tmp_path: Path):
    for bad in ("setuptools", "a/b/c", "/leading", "trailing/"):
        _, proof = parser.read_catalog(_write(tmp_path, [_row(**{"Name with Owner": bad})]))
        assert proof["rejection_reasons"] == {
            "NAME_WITH_OWNER_NOT_OWNER_SLASH_REPO": 1
        }, f"{bad!r} was accepted as an address"


def test_a_non_boolean_fork_flag_is_rejected(tmp_path: Path):
    _, proof = parser.read_catalog(_write(tmp_path, [_row(Fork="maybe")]))
    assert proof["rejection_reasons"] == {"FORK_NOT_BOOLEAN": 1}


def test_every_row_is_either_a_record_or_a_counted_rejection(tmp_path: Path):
    """The accounting control. A parser that drops rows silently is how a
    corpus of millions quietly becomes a smaller one."""
    rows = [
        _row(ID="1"),
        _row(ID="2", SourceRank="x"),
        _row(ID="3", Fork="maybe"),
        _row(ID="4", **{"Name with Owner": "nope"}),
        _row(ID=""),
        _row(ID="6"),
    ]
    records, proof = parser.read_catalog(_write(tmp_path, rows))
    assert proof["rows_total"] == len(rows)
    assert len(records) + proof["rows_rejected"] == proof["rows_total"]
    assert proof["records_parsed"] == len(records) == 2
    assert sum(proof["rejection_reasons"].values()) == 4


# --- nothing TAVONEL computed leaks into a record ----------------------------


def test_the_record_carries_no_field_tavonel_derived():
    """If a popularity or yield score ever appears here, the frame stops being
    external and becomes a TAVONEL judgement wearing a catalogue's name."""
    fields = set(parser.RawCatalogRecord.__dataclass_fields__)
    assert fields == set(parser.COLUMN_CONTRACT)
    for forbidden in ("score", "popularity", "yield", "weight", "priority", "tavonel"):
        assert not any(forbidden in name.casefold() for name in fields), forbidden


def test_the_rank_column_is_the_catalogues_published_sourcerank():
    assert parser.COLUMN_CONTRACT["catalog_rank_value"] == "SourceRank"
    assert parser.COLUMN_CONTRACT["record_id"] == "ID"


def test_the_rank_is_copied_verbatim_including_values_that_look_wrong(tmp_path: Path):
    """A zero or negative published rank is the catalogue's statement, not an
    error to correct. Normalising it here would be editing someone else's data."""
    path = _write(tmp_path, [_row(ID="1", SourceRank="0"), _row(ID="2", SourceRank="-3")])
    records, proof = parser.read_catalog(path)
    assert [r.catalog_rank_value for r in records] == [0, -3]
    assert proof["rows_rejected"] == 0


def test_a_row_lost_between_reading_and_counting_is_refused(tmp_path: Path, monkeypatch):
    """The control the mutation harness demanded.

    The balance check used to compare two numbers the consuming loop maintained
    itself, so deleting it changed nothing -- the guard sat where its failure was
    impossible. It now reconciles the consumer against the reader's own count,
    which is reachable: simulate the reader having seen more rows than the
    consumer was handed, and it must refuse rather than report a smaller corpus.
    """
    real = parser.stream_records

    def lossy(path, tally=None):
        for index, outcome in enumerate(real(path, tally)):
            if index == 1:
                continue  # a row read but never accounted for
            yield outcome

    monkeypatch.setattr(parser, "stream_records", lossy)
    path = _write(tmp_path, [_row(ID="1"), _row(ID="2"), _row(ID="3")])
    with pytest.raises(parser.CatalogParseRefused, match="went missing"):
        parser.read_catalog(path)


def test_the_balance_check_passes_when_nothing_is_lost(tmp_path: Path):
    """The paired positive, so the control above is not merely a broken stub."""
    path = _write(tmp_path, [_row(ID="1"), _row(ID="2"), _row(ID="3")])
    records, proof = parser.read_catalog(path)
    assert proof["rows_total"] == 3
    assert len(records) == 3


# --- the dates the rule compares on ------------------------------------------


def test_a_blank_activity_timestamp_is_refused_and_counted(tmp_path: Path):
    """Found in the real deposit, on the first full selection pass.

    Left to the frame's evaluator this raised `SFIR7Refused` mid-stream and took
    the whole run with it, which is a refusal that reports one row and measures
    none. Refused here it joins the tally, attributable by host like every other
    unusable row.
    """
    records, proof = parser.read_catalog(
        _write(tmp_path, [_row(**{"Last pushed Timestamp": ""})])
    )
    assert records == []
    assert proof["rejection_reasons"] == {"NO_LAST_ACTIVITY_TIMESTAMP": 1}


def test_a_blank_created_timestamp_is_refused_and_counted(tmp_path: Path):
    records, proof = parser.read_catalog(
        _write(tmp_path, [_row(**{"Created Timestamp": ""})])
    )
    assert records == []
    assert proof["rejection_reasons"] == {"NO_CREATED_TIMESTAMP": 1}


def test_an_unparseable_timestamp_is_refused_rather_than_coerced(tmp_path: Path):
    """`0000-00-00` and `not a date` are not dates. Neither becomes one here."""
    rows = [
        _row(ID="1", **{"Name with Owner": "a/b", "Created Timestamp": "0000-00-00 00:00:00 UTC"}),
        _row(ID="2", **{"Name with Owner": "c/d", "Last pushed Timestamp": "not a date"}),
    ]
    records, proof = parser.read_catalog(_write(tmp_path, rows))
    assert records == []
    assert proof["rejection_reasons"] == {
        "CREATED_TIMESTAMP_NOT_A_DATE": 1,
        "LAST_ACTIVITY_TIMESTAMP_NOT_A_DATE": 1,
    }


def test_the_parser_accepts_exactly_what_the_frame_can_read():
    """Bind the parser's date criterion to the evaluator's, so they cannot drift.

    If the frame later widens or narrows what it will read as a date, this goes
    red rather than leaving a class of rows that the parser admits and the
    evaluator dies on -- which is precisely the failure that produced this test.
    """
    import sfir7_frame as frame

    values = [
        "2010-03-01 00:00:00 UTC",
        "2010-03-01",
        "1970-01-01 00:00:00 UTC",
        "",
        "   ",
        "not a date",
        "0000-00-00 00:00:00 UTC",
        "2010-13-01 00:00:00 UTC",
        "20100301",
    ]
    for value in values:
        parser_accepts = parser._is_iso_date(value)
        try:
            frame._as_date(value, label="probe")
            frame_reads = True
        except frame.SFIR7Refused:
            frame_reads = False
        assert parser_accepts is frame_reads, value


def test_a_row_with_good_dates_still_parses(tmp_path: Path):
    """So the four refusals above mean something."""
    records, proof = parser.read_catalog(_write(tmp_path, [_row()]))
    assert len(records) == 1
    assert proof["rejection_reasons"] == {}
