"""Controls for the streaming selection driver and the freeze chain.

The driver exists because 37.6 million projected records do not fit in memory,
and the danger in that is specific: a second implementation of the rule that is
*almost* the declared one produces a roster of real repositories that is not the
roster the rule selects, and nothing about the output looks wrong.

So the load-bearing control here is equivalence -- both paths, same records,
identical output -- and the rest guard the properties streaming cannot check
pairwise.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir7_catalog_parser as catalog_parser  # noqa: E402
import sfir7_frame as frame  # noqa: E402
import sfir7_projection as projection  # noqa: E402
import sfir7_select_roster as roster  # noqa: E402

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

SNAPSHOT_DATE = "2020-01-12"
DIGEST = "sha256:" + "a" * 64


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


def _write(tmp_path: Path, rows: list[list[str]]) -> Path:
    path = tmp_path / "repositories.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


def _rule() -> frame.FrameRule:
    return frame.declared_rule(
        catalog_id="LIBRARIES_IO_OPEN_DATA_1_6_0",
        snapshot_sha256=DIGEST,
        snapshot_date_utc=SNAPSHOT_DATE,
    )


def _universe() -> list[list[str]]:
    """A universe wider than N, so top-N is a real truncation.

    Deliberately mixed: ineligible hosts, ineligible licences, a repository too
    young, one dormant too long, and ranks that interleave with the eligible
    ones so that a wrong ordering would show up as a different roster rather
    than the same one in a different sequence.
    """
    rows: list[list[str]] = []
    licences = ["MIT", "Apache-2.0", "GPL-3.0", "BSD-3-Clause", "mit"]
    for index in range(200):
        rows.append(
            _row(
                ID=str(2000 + index),
                UUID=str(900000 + index),
                **{
                    "Name with Owner": f"owner{index}/repo{index}",
                    "SourceRank": str(index % 40),
                    "License": licences[index % len(licences)],
                },
            )
        )
    # ineligible in each declared way, at ranks that would otherwise win
    rows.append(_row(ID="9001", UUID="990001", SourceRank="99", **{
        "Host Type": "GitLab", "Name with Owner": "gl/top"}))
    rows.append(_row(ID="9002", UUID="990002", SourceRank="99", **{
        "License": "Unlicense", "Name with Owner": "x/unlicensed"}))
    rows.append(_row(ID="9003", UUID="990003", SourceRank="99", **{
        "Created Timestamp": "2019-06-01 00:00:00 UTC", "Name with Owner": "x/young"}))
    rows.append(_row(ID="9004", UUID="990004", SourceRank="99", **{
        "Last pushed Timestamp": "2016-01-01 00:00:00 UTC", "Name with Owner": "x/dormant"}))
    return rows


def _materialised(path: Path) -> frame.CatalogSnapshot:
    records, _ = catalog_parser.read_catalog(path)
    projected = [projection.project(record)[0] for record in records]
    return frame.CatalogSnapshot(
        catalog_id="LIBRARIES_IO_OPEN_DATA_1_6_0",
        snapshot_uri="file://fixture",
        snapshot_sha256=DIGEST,
        snapshot_date_utc=SNAPSHOT_DATE,
        records=tuple(projected),
    )


# --- the load-bearing control -----------------------------------------------


def test_streaming_selection_equals_select_top_n(tmp_path: Path):
    """The reason this driver is allowed to exist.

    If these ever diverge, the frozen roster is not the roster the declared rule
    selects, and every downstream census measures the wrong universe.
    """
    path = _write(tmp_path, _universe())
    rule = _rule()

    reference = frame.select_top_n(_materialised(path), rule)
    streamed = roster.stream_select(path, rule)

    assert [record.record_id for record in streamed["selected"]] == [
        record.record_id for record in reference.selected
    ]
    assert streamed["selected"] == list(reference.selected)
    assert streamed["eligible_count"] == reference.eligible_count
    assert streamed["n"] == reference.n


def test_the_fixture_actually_truncates_so_equivalence_means_something(tmp_path: Path):
    """An equivalence that compares two short selections proves almost nothing."""
    path = _write(tmp_path, _universe())
    streamed = roster.stream_select(path, _rule())
    assert streamed["eligible_count"] > streamed["n"]
    assert len(streamed["selected"]) == streamed["n"]
    assert streamed["selection_is_short"] is False


def test_dispositions_agree_with_the_materialised_path(tmp_path: Path):
    path = _write(tmp_path, _universe())
    rule = _rule()
    _, dispositions = frame.apply_eligibility(_materialised(path), rule)
    reference: dict[str, int] = {}
    for verdict in dispositions.values():
        reference[verdict] = reference.get(verdict, 0) + 1
    assert roster.stream_select(path, rule)["dispositions"] == reference


# --- ordering ----------------------------------------------------------------


def test_the_roster_is_ordered_by_published_rank_descending(tmp_path: Path):
    streamed = roster.stream_select(_write(tmp_path, _universe()), _rule())
    ranks = [record.catalog_rank_value for record in streamed["selected"]]
    assert ranks == sorted(ranks, reverse=True)


def test_ties_on_rank_are_settled_by_the_catalogues_own_record_id(tmp_path: Path):
    """Not by arrival order. Written so a reversed input file changes nothing."""
    rows = [
        _row(ID=str(identifier), UUID=str(identifier), SourceRank="30",
             **{"Name with Owner": f"o{identifier}/r{identifier}"})
        for identifier in (3005, 3001, 3003, 3002, 3004)
    ]
    forward = roster.stream_select(_write(tmp_path, rows), _rule())
    other = tmp_path / "other"
    other.mkdir()
    backward = roster.stream_select(_write(other, list(reversed(rows))), _rule())
    assert [r.record_id for r in forward["selected"]] == [
        r.record_id for r in backward["selected"]
    ]


def test_a_duplicated_catalogue_row_refuses_the_whole_selection(tmp_path: Path):
    """The tie refusal, driven through the driver rather than called directly.

    A unit test of `_require_distinct_keys` proves the function works; it does
    not prove `stream_select` calls it. Deleting the call survived a unit-only
    suite, which is INC-V2-036's shape again: a guard nothing exercises where it
    actually sits.
    """
    rows = [
        _row(ID="7001", UUID="7001", SourceRank="30", **{"Name with Owner": "a/one"}),
        _row(ID="7001", UUID="7002", SourceRank="30", **{"Name with Owner": "b/two"}),
    ]
    with pytest.raises(roster.SelectionRefused, match="not unique"):
        roster.stream_select(_write(tmp_path, rows), _rule())


def test_a_selected_pair_sharing_a_full_ranking_key_is_refused():
    """The tie the tie-breaker cannot settle. Refused, never resolved."""
    rule = _rule()
    record = frame.FrameCatalogRecord(
        record_id="1", host="GitHub", namespace="o", name="r",
        primary_language="Python", spdx_license_id="MIT",
        created_utc="2010-03-01", last_activity_utc="2019-12-30",
        catalog_rank_value=27,
    )
    with pytest.raises(roster.SelectionRefused, match="not unique"):
        roster._require_distinct_keys([record, record], rule)


# --- the strict-total-order proof that replaces the pairwise assertion -------


def _audit(**overrides) -> dict:
    body = {"rows_parsed": 100, "record_id": {"distinct": 100, "duplicates": 0}}
    body.update(overrides)
    return body


def test_a_clean_audit_establishes_the_order():
    proof = roster.require_tie_breaker_proven_unique(_rule(), _audit())
    assert proof["duplicates_measured"] == 0
    assert proof["proven_unique_over_rows"] == 100


def test_a_duplicate_in_the_audit_refuses_the_selection():
    audit = _audit(record_id={"distinct": 99, "duplicates": 1})
    with pytest.raises(roster.SelectionRefused, match="tie-breaker uniqueness"):
        roster.require_tie_breaker_proven_unique(_rule(), audit)


def test_an_audit_that_never_measured_uniqueness_refuses():
    with pytest.raises(roster.SelectionRefused, match="tie-breaker uniqueness"):
        roster.require_tie_breaker_proven_unique(_rule(), {"rows_parsed": 100})


def test_distinct_short_of_parsed_refuses_even_with_zero_duplicates():
    """The two ways of saying it must agree, or neither is evidence."""
    audit = _audit(record_id={"distinct": 42, "duplicates": 0})
    with pytest.raises(roster.SelectionRefused, match="tie-breaker uniqueness"):
        roster.require_tie_breaker_proven_unique(_rule(), audit)


def test_an_inherited_proof_does_not_transfer_to_a_different_tie_breaker():
    """Changing the tie-breaker must go red, not silently reuse record_id's proof."""
    import dataclasses

    rule = dataclasses.replace(_rule(), tie_breaker="catalog_rank_value")
    with pytest.raises(roster.SelectionRefused, match="does not transfer"):
        roster.require_tie_breaker_proven_unique(rule, _audit())


# --- the freeze chain --------------------------------------------------------


def _snapshot_receipt() -> dict:
    return {
        "catalog_id": "LIBRARIES_IO_OPEN_DATA_1_6_0",
        "zenodo_doi": "10.5281/zenodo.3626071",
        "archive_filename": "libraries-1.6.0-2020-01-12.tar.gz",
        "publisher_digest": "md5:4f2275284b86827751bb31ce74238b15",
        "locally_computed_sha256": "sha256:" + "b" * 64,
        "extracted_member_name": "libraries-1.6.0-2020-01-12/repositories-1.6.0-2020-01-12.csv",
        "extracted_member_sha256": DIGEST,
    }


def _freeze(tmp_path: Path) -> dict:
    path = _write(tmp_path, _universe())
    rule = _rule()
    result = roster.stream_select(path, rule)
    result["strict_total_order_proof"] = roster.require_tie_breaker_proven_unique(
        rule, _audit()
    )
    return roster.build_freeze(
        NS, path, result, rule, _snapshot_receipt(), "2026-08-27T00:00:00Z"
    )


def test_the_freeze_binds_every_artifact_that_decides_the_roster(tmp_path: Path):
    body = _freeze(tmp_path)
    chain = body["freeze_chain"]
    for name in roster.FREEZE_CHAIN_MODULES:
        assert chain["modules"][name].startswith("sha256:")
    for name in roster.FREEZE_CHAIN_RECEIPTS:
        assert chain["receipts"][name].startswith("sha256:")
    assert chain["catalog_member_on_disk"].startswith("sha256:")


def test_the_roster_fingerprint_moves_when_the_roster_moves(tmp_path: Path):
    """A fingerprint that survives a changed roster fingerprints nothing."""
    first = _freeze(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    rows = _universe()
    rows[0] = _row(ID="2000", UUID="900000", SourceRank="39",
                   **{"Name with Owner": "owner0/renamed", "License": "MIT"})
    path = _write(other, rows)
    rule = _rule()
    result = roster.stream_select(path, rule)
    result["strict_total_order_proof"] = roster.require_tie_breaker_proven_unique(
        rule, _audit()
    )
    second = roster.build_freeze(
        NS, path, result, rule, _snapshot_receipt(), "2026-08-27T00:00:00Z"
    )
    assert first["roster"] != second["roster"]
    assert first["roster_fingerprint"] != second["roster_fingerprint"]


def test_the_freeze_carries_the_host_uuid_of_every_selected_root(tmp_path: Path):
    """Without it the live census cannot tell a rename from a different repository."""
    body = _freeze(tmp_path)
    assert body["roster"]
    for entry in body["roster"]:
        assert entry["host_uuid"]
        assert entry["name_with_owner"] == f"{entry['namespace']}/{entry['name']}"
    assert body["live_identity_attestation_required"]["on_mismatch"] == "REFUSE"


def test_provenance_only_fields_are_recorded_but_were_not_selected_on(tmp_path: Path):
    body = _freeze(tmp_path)
    for entry in body["roster"]:
        assert "fork" in entry and "status" in entry
    selected_on = {predicate["field"] for predicate in body["frame_rule"]["predicates"]}
    assert selected_on.isdisjoint(projection.WITHHELD_FROM_SELECTION)


def test_the_freeze_states_that_no_census_has_run(tmp_path: Path):
    body = _freeze(tmp_path)
    assert body["downstream_not_run"] == {
        "census_started": False,
        "corpus_spent": False,
        "payload_opened": False,
    }


def test_a_short_selection_is_reported_rather_than_topped_up(tmp_path: Path):
    """The forbidden repair: widening the rule until N roots exist."""
    path = _write(tmp_path, [_row(ID="4001", UUID="4001", **{
        "Name with Owner": "only/one"})])
    result = roster.stream_select(path, _rule())
    assert result["selection_is_short"] is True
    assert result["eligible_count"] == 1
    assert len(result["selected"]) == 1
    assert result["n"] == 50


def test_projection_refusals_do_not_silently_shrink_the_universe(tmp_path: Path):
    """Every row is accounted for: parsed, rejected, or refused."""
    rows = _universe()
    rows.append(_row(ID="5001", UUID="5001", **{"Name with Owner": "no-slash-here"}))
    result = roster.stream_select(_write(tmp_path, rows), _rule())
    accounted = (
        sum(result["dispositions"].values())
        + sum(result["parser_rejections"].values())
        + result["projection_refusals"]
    )
    assert accounted == result["rows_read"]
