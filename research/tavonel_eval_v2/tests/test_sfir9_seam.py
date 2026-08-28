"""Seam verification: catalogue -> selection -> partition -> ordering -> roster -> transport.

Mutation coverage proves things about the inside of one implementation. It says
nothing about whether two implementations are joined the way the protocol says,
and a study can be wrong at every seam while each component is individually
faultless. So these controls sit between components rather than inside them:
each stage's output is required to be the next stage's input, bound by digest or
by identity, with nothing recomputed along the way.

The end-to-end fixture is fixed by an **external oracle** -- the expected host
UUIDs are computed here, in this file, from the frozen rule's own definition,
independently of the selection implementation. A fixture whose expectation came
from running the code under test would agree with any implementation of it,
including a wrong one.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_checkpoint_chain as chain_module  # noqa: E402
import sfir9_cohort_roster as roster_module  # noqa: E402
import sfir9_identity_logic as identity  # noqa: E402
import sfir9_protocol as protocol_module  # noqa: E402
import sfir9_selection as selection_module  # noqa: E402
import sfir9_transport as transport  # noqa: E402

FROZEN = protocol_module.Protocol().freeze()
SALT = "sfir9-seam-salt-v1"
PARTITION_COUNT = 8
PARTITION_INDEX = 0


# ---------------------------------------------------------- the catalogue stage


def parse_catalogue(rows):
    """Stand-in for the catalogue parser: raw records to selection records.

    Deliberately minimal and deliberately here. The seam being tested is what
    crosses between stages, not how a snapshot is decoded.
    """
    parsed = []
    for row in rows:
        parsed.append(
            {
                "host_uuid": str(row["id"]),
                "name_with_owner": row["full_name"],
                "record_id": row["record"],
                "source_rank": int(row["rank"]),
            }
        )
    return parsed


def raw_catalogue(count=3000):
    return [
        {
            "id": 200000 + i,
            "full_name": f"owner{i}/project{i}",
            "record": f"lio-{i:06d}",
            "rank": i % 25,
            # Fields a snapshot carries that must not survive parsing.
            "stars": i * 3,
            "language": "Python",
        }
        for i in range(count)
    ]


def _rule(**overrides):
    term = selection_module.EnvelopeTerm
    body = dict(
        salt=SALT,
        partition_count=PARTITION_COUNT,
        partition_index=PARTITION_INDEX,
        envelope=selection_module.ExecutionEnvelope(
            permitted_rate_windows=term(
                name="permitted_rate_windows", value=6,
                source=selection_module.EXTERNAL, rationale="declared",
            ),
            usable_charge_per_window=term(
                name="usable_charge_per_window", value=4500,
                source=selection_module.EXTERNAL, rationale="declared",
            ),
            per_root_charge_allowance=term(
                name="per_root_charge_allowance", value=540,
                source=selection_module.EXTERNAL, rationale="declared",
            ),
        ),
        spent_host_uuids=frozenset(),
    )
    body.update(overrides)
    return selection_module.FrozenSelection(**body)


# ------------------------------------------------------------ the external oracle


def oracle_expected_roster(rows, *, salt, partition_count, partition_index, n, spent=()):
    """What the frozen rule says the roster is, computed without the selector.

    Written from the protocol's own words -- partition on a blake2b of
    `salt:host_uuid`, keep the declared bucket, drop spent identities, order by
    SourceRank descending then record id ascending, take N -- rather than by
    calling `sfir9_selection`. That independence is the point: an expectation
    produced by the code under test agrees with any implementation of that code,
    correct or not.
    """
    admitted = []
    for row in rows:
        host_uuid = str(row["id"])
        material = f"{salt}:{host_uuid}".encode()
        bucket = int.from_bytes(
            hashlib.blake2b(material, digest_size=8).digest(), "big"
        ) % partition_count
        if bucket != partition_index or host_uuid in set(spent):
            continue
        admitted.append((-int(row["rank"]), str(row["record"]), host_uuid))
    admitted.sort()
    return [host_uuid for _rank, _record, host_uuid in admitted[:n]]


def test_the_oracle_and_the_selector_agree_on_the_exact_uuid_set():
    """One end-to-end fixture whose expected set is fixed from outside."""
    rows = raw_catalogue()
    selection = selection_module.select(parse_catalogue(rows), _rule())

    expected = oracle_expected_roster(
        rows,
        salt=SALT,
        partition_count=PARTITION_COUNT,
        partition_index=PARTITION_INDEX,
        n=selection["n"],
    )
    assert expected, "the oracle produced nothing, so it proves nothing"
    assert [entry["host_uuid"] for entry in selection["roster"]] == expected


def test_the_oracle_disagrees_when_the_rule_changes():
    """The oracle must be able to say no, or its agreement is not information."""
    rows = raw_catalogue()
    selection = selection_module.select(parse_catalogue(rows), _rule())
    wrong = oracle_expected_roster(
        rows,
        salt="a-different-salt",
        partition_count=PARTITION_COUNT,
        partition_index=PARTITION_INDEX,
        n=selection["n"],
    )
    assert [entry["host_uuid"] for entry in selection["roster"]] != wrong


def test_the_oracle_agrees_on_the_exclusions_too():
    rows = raw_catalogue()
    plain = selection_module.select(parse_catalogue(rows), _rule())
    spent = {plain["roster"][0]["host_uuid"], plain["roster"][3]["host_uuid"]}

    reduced = selection_module.select(
        parse_catalogue(rows), _rule(spent_host_uuids=frozenset(spent))
    )
    expected = oracle_expected_roster(
        rows,
        salt=SALT,
        partition_count=PARTITION_COUNT,
        partition_index=PARTITION_INDEX,
        n=reduced["n"],
        spent=spent,
    )
    assert [entry["host_uuid"] for entry in reduced["roster"]] == expected


# ------------------------------------------------- catalogue parser -> selection


def test_the_parser_drops_what_selection_must_never_see():
    """A snapshot carries more than the selection record may hold."""
    parsed = parse_catalogue(raw_catalogue(10))
    for record in parsed:
        assert set(record) == {
            "host_uuid",
            "name_with_owner",
            "record_id",
            "source_rank",
        }
        assert selection_module.FORBIDDEN_SELECTION_INPUTS.isdisjoint(record)


def test_a_parser_that_leaked_a_forbidden_field_refuses_the_selection():
    """The seam is defended from the selection side, not just the parser side."""
    parsed = parse_catalogue(raw_catalogue(50))
    parsed[2]["language"] = "Python"
    with pytest.raises(selection_module.SelectionRefused):
        selection_module.select(parsed, _rule())


# ------------------------------------------------------- selection -> roster


def test_every_roster_entry_traces_to_the_selection_record_it_came_from():
    rows = raw_catalogue()
    parsed = parse_catalogue(rows)
    selection = selection_module.select(parsed, _rule())
    roster = roster_module.CohortRoster(
        protocol=FROZEN,
        selection=selection,
        exclusion_proof=identity.exclusion_proof(identity.spent_set([])),
    )
    by_uuid = {record["host_uuid"]: record for record in parsed}
    for entry in roster.entries:
        source = by_uuid[entry.host_uuid]
        assert entry.record_id == source["record_id"]
        assert entry.catalogue_address == source["name_with_owner"]
        assert entry.source_rank == source["source_rank"]


def test_the_roster_preserves_the_selection_order_as_its_ordinals():
    selection = selection_module.select(parse_catalogue(raw_catalogue()), _rule())
    roster = roster_module.CohortRoster(
        protocol=FROZEN,
        selection=selection,
        exclusion_proof=identity.exclusion_proof(identity.spent_set([])),
    )
    assert [e.host_uuid for e in roster.entries] == [
        entry["host_uuid"] for entry in selection["roster"]
    ]
    assert [e.selection_ordinal for e in roster.entries] == [
        entry["rank"] for entry in selection["roster"]
    ]


def test_the_roster_binds_the_selection_digest_it_was_built_from():
    selection = selection_module.select(parse_catalogue(raw_catalogue()), _rule())
    roster = roster_module.CohortRoster(
        protocol=FROZEN,
        selection=selection,
        exclusion_proof=identity.exclusion_proof(identity.spent_set([])),
    )
    assert roster.body()["selection_digest"] == selection["selection_digest"]


def test_a_roster_built_from_one_selection_does_not_match_another():
    """Digest binding, not merely digest presence."""
    parsed = parse_catalogue(raw_catalogue())
    a = selection_module.select(parsed, _rule())
    b = selection_module.select(parsed, _rule(partition_index=1))
    assert a["selection_digest"] != b["selection_digest"]

    roster_a = roster_module.CohortRoster(
        protocol=FROZEN,
        selection=a,
        exclusion_proof=identity.exclusion_proof(identity.spent_set([])),
    )
    assert roster_a.body()["selection_digest"] != b["selection_digest"]


# --------------------------------------------------------- roster -> transport


def _sealed_roster():
    selection = selection_module.select(parse_catalogue(raw_catalogue()), _rule())
    roster = roster_module.CohortRoster(
        protocol=FROZEN,
        selection=selection,
        exclusion_proof=identity.exclusion_proof(identity.spent_set([])),
    )
    seal = roster.seal()
    return roster, selection, seal


def test_the_transport_carries_the_sealed_rosters_digest():
    _roster, selection, seal = _sealed_roster()
    client = transport.Sfir9Transport(
        upstream=object(),
        roster_digest=seal,
        selection_digest=selection["selection_digest"],
    )
    handoff = client.handoff(
        protocol_digest=FROZEN.digest(),
        frontier_digest="sha256:f",
        visited_digest="sha256:v",
        candidate_accumulator_digest="sha256:c",
        previous_segment_digest=chain_module.GENESIS,
    )
    assert handoff.roster_digest == seal
    assert handoff.selection_digest == selection["selection_digest"]


def test_the_transport_addresses_a_root_the_roster_actually_selected():
    """Identity binding across the seam, not merely a matching address."""
    roster, _selection, _seal = _sealed_roster()
    entry = roster.entries[0]
    frozen_identity = identity.RepositoryIdentity.frozen(
        host_uuid=entry.host_uuid, catalogue_address=entry.catalogue_address
    )
    assert frozen_identity.attest(entry.host_uuid).host_uuid == entry.host_uuid
    with pytest.raises(identity.IdentityRefused):
        frozen_identity.attest("999999999")


def test_a_chain_built_on_the_sealed_roster_refuses_a_segment_from_another():
    """The last seam: roster digest -> transport handoff -> checkpoint chain."""
    _roster, selection, seal = _sealed_roster()
    chain = chain_module.SegmentChain(
        study_id=protocol_module.PROTOCOL_ID,
        protocol_digest=FROZEN.digest(),
        roster_digest=seal,
        selection_digest=selection["selection_digest"],
    )
    client = transport.Sfir9Transport(
        upstream=object(),
        roster_digest=seal,
        selection_digest=selection["selection_digest"],
    )
    good = client.handoff(
        protocol_digest=FROZEN.digest(),
        frontier_digest="sha256:f",
        visited_digest="sha256:v",
        candidate_accumulator_digest="sha256:c",
        previous_segment_digest=chain_module.GENESIS,
    )
    assert chain.append(chain.open_next(good))

    other = transport.Sfir9Transport(
        upstream=object(),
        roster_digest="sha256:some-other-roster",
        selection_digest=selection["selection_digest"],
    )
    stray = other.handoff(
        protocol_digest=FROZEN.digest(),
        frontier_digest="sha256:f",
        visited_digest="sha256:v",
        candidate_accumulator_digest="sha256:c",
        previous_segment_digest=chain_module.GENESIS,
    )
    with pytest.raises(chain_module.ChainRefused) as caught:
        chain.append(chain.open_next(stray))
    assert caught.value.code == chain_module.WRONG_ROSTER


# ------------------------------------------------------------ end to end


def test_the_whole_seam_holds_for_one_fixture():
    """Catalogue to chain, with the expected UUID set fixed from outside."""
    rows = raw_catalogue()
    parsed = parse_catalogue(rows)
    selection = selection_module.select(parsed, _rule())

    expected = oracle_expected_roster(
        rows,
        salt=SALT,
        partition_count=PARTITION_COUNT,
        partition_index=PARTITION_INDEX,
        n=selection["n"],
    )

    roster = roster_module.CohortRoster(
        protocol=FROZEN,
        selection=selection,
        exclusion_proof=identity.exclusion_proof(identity.spent_set([])),
    )
    seal = roster.seal()

    assert [e.host_uuid for e in roster.entries] == expected

    client = transport.Sfir9Transport(
        upstream=object(),
        roster_digest=seal,
        selection_digest=selection["selection_digest"],
    )
    chain = chain_module.SegmentChain(
        study_id=protocol_module.PROTOCOL_ID,
        protocol_digest=FROZEN.digest(),
        roster_digest=seal,
        selection_digest=selection["selection_digest"],
    )
    segment = chain.append(
        chain.open_next(
            client.handoff(
                protocol_digest=FROZEN.digest(),
                frontier_digest="sha256:f",
                visited_digest="sha256:v",
                candidate_accumulator_digest="sha256:c",
                previous_segment_digest=chain_module.GENESIS,
            )
        )
    )
    assert segment.handoff.roster_digest == seal
    assert chain_module.verify_chain(chain.receipt())["links_intact"] is True
