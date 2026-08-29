"""Controls for cohort generation, the one step that cannot be rerun.

The end-to-end control builds a synthetic catalogue with the publisher's real
column names and checks the roster against an oracle written from the frozen
protocol's words rather than from the selection module -- comparing the module
with itself would agree by construction.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir7_roots  # noqa: E402
import sfir9_generate_roster as gen  # noqa: E402
import sfir9_protocol as protocol_module  # noqa: E402

COLUMNS = [
    "ID",
    "UUID",
    "Host Type",
    "Name with Owner",
    "SourceRank",
    "Created Timestamp",
    "Last pushed Timestamp",
    "License",
    "Language",
    "Fork",
    "Status",
]

ELIGIBLE = {
    "Host Type": "GitHub",
    "License": "MIT",
    "Created Timestamp": "2015-06-01 00:00:00 UTC",
    "Last pushed Timestamp": "2019-06-01 00:00:00 UTC",
    "Language": "Python",
    "Fork": "false",
    "Status": "",
}


def _row(index: int, **overrides):
    row = {
        "ID": str(100000 + index),
        "UUID": str(900000 + index),
        "Name with Owner": f"owner{index}/repo{index}",
        # Ranks repeat deliberately, so record_id has to break ties.
        "SourceRank": str(index % 30),
        **ELIGIBLE,
        **overrides,
    }
    return [row[column] for column in COLUMNS]


def in_partition(host_uuid: str) -> bool:
    """The frozen partition test, written out, so a fixture can aim at it."""
    material = f"{protocol_module.SELECTION_SALT}:{host_uuid}".encode()
    bucket = (
        int.from_bytes(hashlib.blake2b(material, digest_size=8).digest(), "big")
        % protocol_module.PARTITION_COUNT
    )
    return bucket == protocol_module.PARTITION_INDEX


def admitted_uuid(seed: int) -> str:
    """A host id that lands in the selected partition.

    Rows that do not land there never reach a roster, so a test asserting on
    roster membership has to aim at the partition or it is asserting on a
    coin flip.
    """
    candidate = seed
    while not in_partition(str(candidate)):
        candidate += 1
    return str(candidate)


def _catalogue(tmp_path, rows):
    path = tmp_path / "repositories.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    return path


def _binding(path, *, predicates=None):
    """The shape `require_authorities` would have returned, without the 10 GB."""
    return {
        "binding_digest": "sha256:" + "b" * 64,
        "member_verification": {"path": str(path)},
        "inherited_frame": {
            "predicates": predicates
            if predicates is not None
            else [
                {"field": "host", "op": "eq", "value": "github"},
                {"field": "spdx_license_id", "op": "in", "value": ["MIT", "Apache-2.0"]},
                {"field": "created_utc", "op": "on_or_before", "value": "2017-01-12"},
                {"field": "last_activity_utc", "op": "on_or_after", "value": "2019-01-12"},
            ]
        },
    }


def oracle_roster(rows, spent):
    """The frozen rule, written out from the protocol rather than imported.

    salt + host_uuid -> blake2b -> 64 partitions -> partition 0, spent removed,
    then SourceRank descending and record_id ascending, then the first N.
    """
    admitted = []
    for row in rows:
        record = dict(zip(COLUMNS, row, strict=True))
        host_uuid = record["UUID"]
        material = f"{protocol_module.SELECTION_SALT}:{host_uuid}".encode()
        bucket = (
            int.from_bytes(hashlib.blake2b(material, digest_size=8).digest(), "big")
            % protocol_module.PARTITION_COUNT
        )
        if bucket != protocol_module.PARTITION_INDEX or host_uuid in spent:
            continue
        admitted.append((-int(record["SourceRank"]), record["ID"], host_uuid))
    admitted.sort()
    n = (
        protocol_module.PERMITTED_RATE_WINDOWS * protocol_module.USABLE_CHARGE_PER_WINDOW
    ) // protocol_module.PER_ROOT_CHARGE_ALLOWANCE
    return [host_uuid for _rank, _record, host_uuid in admitted[:n]]


@pytest.fixture
def sandbox(tmp_path):
    (tmp_path / "receipts").mkdir()
    return tmp_path


def _generate(sandbox, binding, monkeypatch, **overrides):
    monkeypatch.setattr(
        gen,
        "require_authorities",
        lambda _ns, _root: {
            "freeze": {"freeze_digest": "sha256:f", "instrument_commit": "abc123"},
            "binding": binding,
        },
    )
    return gen.generate(
        namespace=sandbox, output=sandbox / "receipts/roster.json", **overrides
    )


# --- the end-to-end control ------------------------------------------------


def test_the_roster_matches_an_independently_written_rule(sandbox, monkeypatch):
    """Enough rows that the partition holds more than N, so N truncates."""
    rows = [_row(index) for index in range(6400)]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)

    spent = {str(entry["host_uuid"]) for entry in sfir7_roots.frozen_roster()}
    expected = oracle_roster(rows, spent)
    produced = [entry["host_uuid"] for entry in report["roster"]["entries"]]

    assert produced == expected
    assert len(produced) == 50
    assert report["selection"]["roster_is_short"] is False
    assert gen.verify(report)["verified"]


def test_a_partition_smaller_than_n_yields_a_short_roster(sandbox, monkeypatch):
    """A shortfall is a result, not something to widen the partition until it goes away."""
    rows = [_row(index) for index in range(400)]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    produced = [entry["host_uuid"] for entry in report["roster"]["entries"]]
    spent = {str(entry["host_uuid"]) for entry in sfir7_roots.frozen_roster()}
    assert produced == oracle_roster(rows, spent)
    assert len(produced) < 50
    assert report["selection"]["roster_is_short"] is True


# --- eligibility is inherited, not reimplemented ---------------------------


@pytest.mark.parametrize(
    ("overrides", "disposition"),
    [
        ({"Host Type": "GitLab"}, "REJECTED_host_eq"),
        ({"License": "GPL-1.0"}, "REJECTED_spdx_license_id_in"),
        ({"Created Timestamp": "2020-01-01 00:00:00 UTC"}, "REJECTED_created_utc_on_or_before"),
        (
            {"Last pushed Timestamp": "2018-01-01 00:00:00 UTC"},
            "REJECTED_last_activity_utc_on_or_after",
        ),
    ],
)
def test_each_inherited_predicate_rejects_and_says_which(
    sandbox, monkeypatch, overrides, disposition
):
    rows = [_row(0), _row(1, **overrides)]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    dispositions = report["catalogue_accounting"]["eligibility_dispositions"]
    assert dispositions[disposition] == 1
    assert dispositions["ELIGIBLE"] == 1


def test_the_first_failing_predicate_is_the_one_recorded(sandbox, monkeypatch):
    """Declared order, so a disposition is a function of the rule's text."""
    rows = [_row(0, **{"Host Type": "GitLab", "License": "GPL-1.0"})]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    dispositions = report["catalogue_accounting"]["eligibility_dispositions"]
    assert dispositions == {"REJECTED_host_eq": 1}


def test_a_row_with_no_host_uuid_is_counted_not_guessed(sandbox, monkeypatch):
    """The partition is keyed on it, so a row without one cannot be placed."""
    rows = [_row(0, UUID=admitted_uuid(900000)), _row(1, UUID="")]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    dispositions = report["catalogue_accounting"]["eligibility_dispositions"]
    assert dispositions["ELIGIBLE_BUT_NO_HOST_UUID"] == 1
    assert len(report["roster"]["entries"]) == 1
    assert report["roster"]["entries"][0]["host_uuid"] == admitted_uuid(900000)


def test_unreadable_rows_are_tallied_by_reason(sandbox, monkeypatch):
    rows = [_row(0), _row(1, SourceRank=""), _row(2, **{"Name with Owner": "no-slash"})]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    accounting = report["catalogue_accounting"]
    assert accounting["unreadable_rows"]["NO_PUBLISHED_RANK"] == 1
    assert accounting["unreadable_rows"]["NAME_WITH_OWNER_NOT_OWNER_SLASH_REPO"] == 1
    assert accounting["unreadable_total"] == 2
    assert accounting["rows_read"] == 3


def test_the_three_accounting_layers_are_separate(sandbox, monkeypatch):
    """One 'rows dropped' total would hide a header change behind a licence filter."""
    rows = [_row(0), _row(1, SourceRank=""), _row(2, **{"Host Type": "GitLab"})]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    accounting = report["catalogue_accounting"]
    assert accounting["unreadable_total"] == 1
    assert accounting["eligibility_dispositions"]["REJECTED_host_eq"] == 1
    assert "exclusions" in report["selection"]


def test_the_predicates_come_from_the_binding_not_from_here(sandbox, monkeypatch):
    """Swap the inherited rule and the outcome must follow it."""
    rows = [
        _row(0, Language="Python", UUID=admitted_uuid(910000)),
        _row(1, Language="Rust", UUID=admitted_uuid(920000)),
    ]
    binding = _binding(
        _catalogue(sandbox, rows),
        predicates=[{"field": "primary_language", "op": "in", "value": ["Rust"]}],
    )
    report = _generate(sandbox, binding, monkeypatch)
    assert report["catalogue_accounting"]["eligible"] == 1
    assert report["roster"]["entries"][0]["record_id"] == "100001"


# --- spent identities ------------------------------------------------------


def test_a_spent_identity_never_reaches_the_roster(sandbox, monkeypatch):
    spent = [str(entry["host_uuid"]) for entry in sfir7_roots.frozen_roster()]
    rows = [_row(index, UUID=uuid) for index, uuid in enumerate(spent)]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    produced = {entry["host_uuid"] for entry in report["roster"]["entries"]}
    assert produced.isdisjoint(spent)
    assert report["spent_identities_excluded"] == 50


# --- the refusals ----------------------------------------------------------


def test_a_second_generation_is_refused(sandbox, monkeypatch):
    rows = [_row(index) for index in range(200)]
    binding = _binding(_catalogue(sandbox, rows))
    _generate(sandbox, binding, monkeypatch)
    with pytest.raises(gen.GenerationRefused) as caught:
        _generate(sandbox, binding, monkeypatch)
    assert caught.value.code == gen.ALREADY_OPENED


def test_an_absent_freeze_is_refused(sandbox):
    with pytest.raises(gen.GenerationRefused) as caught:
        gen.require_authorities(sandbox, NS.parents[1])
    assert caught.value.code == gen.NO_FREEZE


def test_a_freeze_that_does_not_verify_is_refused(sandbox, monkeypatch):
    (sandbox / gen.FREEZE_RECEIPT).write_text(json.dumps({"state": "TAMPERED"}), encoding="utf-8")
    with pytest.raises(gen.GenerationRefused) as caught:
        gen.require_authorities(sandbox, NS.parents[1])
    assert caught.value.code == gen.FREEZE_INVALID


def test_an_absent_binding_is_refused(sandbox, monkeypatch):
    import sfir9_freeze as freeze_module

    (sandbox / gen.FREEZE_RECEIPT).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        freeze_module, "verify", lambda _report: {"verified": True, "problems": []}
    )
    with pytest.raises(gen.GenerationRefused) as caught:
        gen.require_authorities(sandbox, NS.parents[1])
    assert caught.value.code == gen.NO_BINDING


def test_a_binding_that_does_not_rederive_is_refused(sandbox, monkeypatch):
    """The receipt says it held once. This asks now, against these bytes."""
    import sfir9_cohort_input as cohort_input
    import sfir9_freeze as freeze_module

    (sandbox / gen.FREEZE_RECEIPT).write_text("{}", encoding="utf-8")
    (sandbox / gen.BINDING_RECEIPT).write_text(
        json.dumps({"binding_digest": "sha256:stale"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        freeze_module, "verify", lambda _report: {"verified": True, "problems": []}
    )
    monkeypatch.setattr(
        cohort_input, "binding", lambda **_kwargs: {"binding_digest": "sha256:live"}
    )
    with pytest.raises(gen.GenerationRefused) as caught:
        gen.require_authorities(sandbox, NS.parents[1])
    assert caught.value.code == gen.BINDING_DRIFTED


def test_a_binding_that_rederives_is_accepted(sandbox, monkeypatch):
    """Control for the test above."""
    import sfir9_cohort_input as cohort_input
    import sfir9_freeze as freeze_module

    (sandbox / gen.FREEZE_RECEIPT).write_text("{}", encoding="utf-8")
    (sandbox / gen.BINDING_RECEIPT).write_text(
        json.dumps({"binding_digest": "sha256:same"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        freeze_module, "verify", lambda _report: {"verified": True, "problems": []}
    )
    monkeypatch.setattr(
        cohort_input, "binding", lambda **_kwargs: {"binding_digest": "sha256:same"}
    )
    assert gen.require_authorities(sandbox, NS.parents[1])["binding"]["binding_digest"] == (
        "sha256:same"
    )


# --- the roster is sealed --------------------------------------------------


def test_the_roster_is_sealed_before_the_receipt_exists(sandbox, monkeypatch):
    rows = [_row(index) for index in range(200)]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    assert report["roster"]["sealed"] is True
    assert report["roster_seal"].startswith("sha256:")
    assert report["roster"]["roster_digest"] == report["roster_seal"]


def test_no_observation_field_reaches_the_roster(sandbox, monkeypatch):
    rows = [_row(index) for index in range(200)]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    for entry in report["roster"]["entries"]:
        assert set(entry) <= set(report["roster"]["permitted_entry_fields"])


# --- verification ----------------------------------------------------------


def test_an_edited_receipt_fails_verification(sandbox, monkeypatch):
    rows = [_row(index) for index in range(200)]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    report["spent_identities_excluded"] = 0
    assert not gen.verify(report)["verified"]


def test_broken_ordinals_fail_verification(sandbox, monkeypatch):
    rows = [_row(index) for index in range(200)]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    report["roster"]["entries"][0]["selection_ordinal"] = 7
    problems = gen.verify(report)["problems"]
    assert any("ordinals" in problem for problem in problems)


def test_an_unsealed_roster_fails_verification(sandbox, monkeypatch):
    rows = [_row(index) for index in range(200)]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    report["roster_seal"] = ""
    problems = gen.verify(report)["problems"]
    assert any("sealed" in problem for problem in problems)


# --- the module decides nothing --------------------------------------------


def test_the_generator_holds_no_quantity_of_its_own():
    """Every number it could have held is one someone could have chosen later.

    N, the partition, the salt, the predicates and the eligibility fields all
    live elsewhere. A bare integer literal appearing here is worth a second look.
    """
    source = (NS / "tools/sfir9_generate_roster.py").read_text(encoding="utf-8")
    for forbidden in ("750", "600", "1000", "= 50", "64", "0.8"):
        assert forbidden not in source, forbidden


def test_a_refused_generation_exits_nonzero(sandbox, monkeypatch, capsys):
    def refuse(**_kwargs):
        raise gen.GenerationRefused(gen.NO_FREEZE, "absent")

    monkeypatch.setattr(gen, "generate", refuse)
    assert gen.main(["--namespace", str(sandbox)]) == 1
    assert "REFUSED" in capsys.readouterr().out

def test_an_ineligible_row_inside_the_partition_never_reaches_the_roster(sandbox, monkeypatch):
    """Aimed at the partition, or the test is a coin flip.

    A row that fails a predicate but lands where the roster is drawn from is the
    only row that can prove the eligibility filter is wired into the selection
    rather than merely counted.
    """
    rows = [
        _row(0, UUID=admitted_uuid(930000)),
        _row(1, UUID=admitted_uuid(940000), **{"Host Type": "GitLab"}),
    ]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    produced = [entry["host_uuid"] for entry in report["roster"]["entries"]]
    assert produced == [admitted_uuid(930000)]
    assert admitted_uuid(940000) not in produced


def test_the_spent_set_is_keyed_on_the_host_id_not_the_address(sandbox, monkeypatch):
    """Addresses move; the numeric id is what an earlier study actually spent.

    The spent entry here carries an address that matches nothing in the
    catalogue, so a generator keying on `name_with_owner` would exclude nobody.
    """
    spent_uuid = admitted_uuid(950000)
    monkeypatch.setattr(
        sfir7_roots,
        "frozen_roster",
        lambda: ({"host_uuid": spent_uuid, "name_with_owner": "someone/else"},),
    )
    rows = [_row(0, UUID=spent_uuid), _row(1, UUID=admitted_uuid(960000))]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    produced = [entry["host_uuid"] for entry in report["roster"]["entries"]]
    assert produced == [admitted_uuid(960000)]
    assert report["selection"]["exclusions"]["host_uuids"] == [spent_uuid]


def test_the_exclusion_proof_travels_into_the_roster(sandbox, monkeypatch):
    """A reader a year from now sees which identities were withheld, and why."""
    spent_uuid = admitted_uuid(970000)
    monkeypatch.setattr(
        sfir7_roots,
        "frozen_roster",
        lambda: ({"host_uuid": spent_uuid, "name_with_owner": "someone/else"},),
    )
    rows = [_row(0, UUID=spent_uuid), _row(1, UUID=admitted_uuid(980000))]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    proof = report["roster"]["exclusion_proof"]
    assert proof["host_uuids"] == [spent_uuid]
    assert proof["count"] == 1
    assert proof == report["selection"]["exclusions"]


def test_the_receipt_binds_the_two_authorities_it_ran_under(sandbox, monkeypatch):
    """A roster that does not name its freeze and its input is unreproducible."""
    rows = [_row(index) for index in range(200)]
    binding = _binding(_catalogue(sandbox, rows))
    report = _generate(sandbox, binding, monkeypatch)
    assert report["instrument_freeze"] == "sha256:f"
    assert report["instrument_commit"] == "abc123"
    assert report["cohort_input_binding"] == binding["binding_digest"]


def test_the_receipt_says_the_cohort_establishes_nothing_about_capacity(sandbox, monkeypatch):
    """No repository here has been contacted. C and Q do not exist yet."""
    rows = [_row(index) for index in range(200)]
    report = _generate(sandbox, _binding(_catalogue(sandbox, rows)), monkeypatch)
    assert "C and Q do not exist yet" in report["what_this_does_not_establish"]
    assert "has been contacted" in report["what_this_does_not_establish"]

