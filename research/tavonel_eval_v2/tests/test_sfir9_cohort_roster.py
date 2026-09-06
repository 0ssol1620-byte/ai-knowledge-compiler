"""Controls for the SFIR9 cohort roster.

Synthetic fixtures throughout. The real Libraries.io snapshot stays closed until
every component is frozen, and a control suite that opened it would have looked
at the roster before the rule that produces it was fixed -- which is the exact
ordering this component exists to enforce.

Two properties carry the file. A roster may hold catalogue and selection facts
and nothing else, so an entry offering `candidate_count` or `renamed` refuses the
whole build. And a roster is written once: sealing is not idempotent, because a
caller sealing twice has lost track of which roster is the sealed one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_cohort_roster as roster_module  # noqa: E402
import sfir9_identity_logic as identity  # noqa: E402
import sfir9_protocol as protocol_module  # noqa: E402
import sfir9_selection as selection_module  # noqa: E402

FROZEN = protocol_module.Protocol().freeze()


def _catalogue(count=4000):
    return [
        {
            "host_uuid": str(100000 + i),
            "name_with_owner": f"org{i}/repo{i}",
            "record_id": f"r{i:06d}",
            "source_rank": i % 30,
        }
        for i in range(count)
    ]


def _rule(**overrides):
    body = dict(
        salt="sfir9-frozen-salt-v1",
        partition_count=8,
        partition_index=0,
        envelope=selection_module.ExecutionEnvelope(
            permitted_rate_windows=selection_module.EnvelopeTerm(
                name="permitted_rate_windows", value=6,
                source=selection_module.EXTERNAL, rationale="declared",
            ),
            usable_charge_per_window=selection_module.EnvelopeTerm(
                name="usable_charge_per_window", value=4500,
                source=selection_module.EXTERNAL, rationale="declared",
            ),
            per_root_charge_allowance=selection_module.EnvelopeTerm(
                name="per_root_charge_allowance", value=540,
                source=selection_module.EXTERNAL, rationale="declared",
            ),
        ),
        spent_host_uuids=frozenset(),
    )
    body.update(overrides)
    return selection_module.FrozenSelection(**body)


def _proof(records=()):
    return identity.exclusion_proof(identity.spent_set(records))


def _roster(*, protocol=FROZEN, selection=None, proof=None, catalogue=None):
    selection = selection or selection_module.select(catalogue or _catalogue(), _rule())
    return roster_module.CohortRoster(
        protocol=protocol,
        selection=selection,
        exclusion_proof=proof if proof is not None else _proof(),
    )


# ------------------------------------------------------------ what it holds


def test_an_entry_holds_exactly_the_six_declared_fields():
    entry = _roster().entries[0]
    assert set(entry.as_dict()) == set(roster_module.PERMITTED_ENTRY_FIELDS)
    assert set(roster_module.RosterEntry.__dataclass_fields__) == set(
        roster_module.PERMITTED_ENTRY_FIELDS
    )


def test_the_declared_fields_are_the_ones_the_ruling_names():
    assert set(roster_module.PERMITTED_ENTRY_FIELDS) == {
        "record_id",
        "host_uuid",
        "catalogue_address",
        "source_rank",
        "partition_digest",
        "selection_ordinal",
    }


def test_every_entry_carries_real_catalogue_values():
    roster = _roster()
    for entry in roster.entries:
        assert entry.record_id.startswith("r")
        assert "/" in entry.catalogue_address
        assert entry.partition_digest.startswith("sha256:")
        assert isinstance(entry.source_rank, int)


@pytest.mark.parametrize(
    "ordinals",
    [
        [0, 1, 2],       # generated from a zero-based enumerate
        [1, 2, 4],       # a selected root that was lost
        [1, 2, 2],       # two roots claiming one rank
        [3, 2, 1],       # ranked, then reordered
    ],
)
def test_malformed_ordinals_refuse(ordinals):
    """The check guards the generation step, so it is driven at that step.

    Nothing on the public path can produce these today -- `enumerate` is
    correct -- which is exactly why the check has to be exercised directly. A
    guard only ever run against input that cannot be wrong has never been run.
    """
    entries = [
        roster_module.RosterEntry(
            record_id=f"r{i}",
            host_uuid=str(100 + i),
            catalogue_address=f"o{i}/r{i}",
            source_rank=1,
            partition_digest="sha256:p",
            selection_ordinal=ordinal,
        )
        for i, ordinal in enumerate(ordinals)
    ]
    with pytest.raises(roster_module.RosterRefused) as caught:
        roster_module.CohortRoster._check_wellformed(entries)
    assert caught.value.code == roster_module.BROKEN_ORDINALS


def test_the_ordinals_are_one_to_n_in_order():
    roster = _roster()
    assert [e.selection_ordinal for e in roster.entries] == list(
        range(1, len(roster.entries) + 1)
    )


# -------------------------------------------------- no observation gets in


@pytest.mark.parametrize("forbidden", sorted(roster_module.FORBIDDEN_ROSTER_FIELDS))
def test_a_selected_row_carrying_a_forbidden_field_refuses_the_build(forbidden):
    selection = selection_module.select(_catalogue(), _rule())
    selection["roster"][3][forbidden] = 1
    with pytest.raises(roster_module.RosterRefused) as caught:
        _roster(selection=selection)
    assert caught.value.code == roster_module.OBSERVATION_IN_ROSTER


def test_the_forbidden_list_names_the_earlier_studies_output_and_the_live_facts():
    """Both kinds: what SFIR7 saw, and what SFIR9 has not learned yet."""
    assert {
        "candidate_count",
        "tree_size",
        "traversal_difficulty",
        "completion_status",
    } <= roster_module.FORBIDDEN_ROSTER_FIELDS
    assert {"rename_status", "renamed", "canonical_address"} <= (
        roster_module.FORBIDDEN_ROSTER_FIELDS
    )


def test_a_clean_selection_builds_without_complaint():
    assert len(_roster().entries) == 50


# ----------------------------------------------------------- the partition


def test_the_partition_digest_does_not_expose_the_salt():
    roster = _roster()
    assert "sfir9-frozen-salt-v1" not in str(roster.receipt())


def test_the_partition_digest_changes_with_the_identity():
    a = roster_module.partition_digest(
        salt_digest="sha256:s", partition_count=8, partition_index=0, host_uuid="1"
    )
    b = roster_module.partition_digest(
        salt_digest="sha256:s", partition_count=8, partition_index=0, host_uuid="2"
    )
    assert a != b


@pytest.mark.parametrize(
    "changed",
    [
        {"salt_digest": "sha256:other"},
        {"partition_count": 16},
        {"partition_index": 1},
    ],
)
def test_the_partition_digest_changes_with_every_declared_term(changed):
    base = dict(
        salt_digest="sha256:s", partition_count=8, partition_index=0, host_uuid="1"
    )
    assert roster_module.partition_digest(**{**base, **changed}) != (
        roster_module.partition_digest(**base)
    )


def test_each_entrys_partition_digest_is_reproducible_from_the_declared_terms():
    """A function of the frozen rule and the identity, and of nothing else.

    Derived from the whole partition record instead, it would move with
    `rows_outside_partition` -- a fact about how big the catalogue happened to be,
    which is an observation and not a property of the rule.
    """
    selection = selection_module.select(_catalogue(), _rule())
    partition = selection["partition"]
    roster = _roster(selection=selection)

    for entry in roster.entries:
        assert entry.partition_digest == roster_module.partition_digest(
            salt_digest=partition["salt_digest"],
            partition_count=partition["partition_count"],
            partition_index=partition["partition_index"],
            host_uuid=entry.host_uuid,
        )


def test_the_partition_digest_does_not_move_with_the_size_of_the_catalogue():
    """The same root in a bigger catalogue is in the same bucket."""
    small = selection_module.select(_catalogue(1200), _rule())
    large = selection_module.select(_catalogue(4000), _rule())
    small_digests = {
        e.host_uuid: e.partition_digest for e in _roster(selection=small).entries
    }
    large_digests = {
        e.host_uuid: e.partition_digest for e in _roster(selection=large).entries
    }
    shared = set(small_digests) & set(large_digests)
    assert shared
    for host_uuid in shared:
        assert small_digests[host_uuid] == large_digests[host_uuid]


def test_two_roots_in_one_roster_have_different_partition_digests():
    roster = _roster()
    digests = {entry.partition_digest for entry in roster.entries}
    assert len(digests) == len(roster.entries)


# --------------------------------------------------------- spent exclusion


def test_a_spent_root_appearing_in_the_roster_refuses():
    selection = selection_module.select(_catalogue(), _rule())
    spent = selection["roster"][0]["host_uuid"]
    with pytest.raises(roster_module.RosterRefused) as caught:
        _roster(
            selection=selection,
            proof=_proof([{"host_uuid": spent, "spent_by_study": "SFIR7"}]),
        )
    assert caught.value.code == roster_module.SPENT_IN_ROSTER


def test_the_sealed_roster_carries_the_exclusion_proof():
    """A reader a year from now must see which identities were withheld and why."""
    proof = _proof([{"host_uuid": "999999", "spent_by_study": "SFIR7"}])
    roster = _roster(proof=proof)
    body = roster.body()
    assert body["exclusion_proof"]["reason"] == identity.SPENT
    assert body["exclusion_proof"]["host_uuids"] == ["999999"]


def test_the_roster_digest_covers_the_exclusion_proof():
    with_proof = _roster(proof=_proof([{"host_uuid": "999999", "spent_by_study": "SFIR7"}]))
    without = _roster()
    assert with_proof.digest() != without.digest()


# ------------------------------------------------------------ well-formed


def test_a_repeated_repository_refuses():
    selection = selection_module.select(_catalogue(), _rule())
    selection["roster"][1] = dict(selection["roster"][0])
    selection["roster"][1]["record_id"] = "r999999"
    with pytest.raises(roster_module.RosterRefused) as caught:
        _roster(selection=selection)
    assert caught.value.code == roster_module.DUPLICATE
    assert "inflate the census" in str(caught.value)


def test_a_repeated_catalogue_record_refuses():
    selection = selection_module.select(_catalogue(), _rule())
    selection["roster"][1]["record_id"] = selection["roster"][0]["record_id"]
    with pytest.raises(roster_module.RosterRefused) as caught:
        _roster(selection=selection)
    assert caught.value.code == roster_module.DUPLICATE


def test_a_roster_entry_cannot_be_identified_by_an_address():
    selection = selection_module.select(_catalogue(), _rule())
    selection["roster"][0]["host_uuid"] = "facebook/react"
    with pytest.raises(identity.IdentityRefused) as caught:
        _roster(selection=selection)
    assert caught.value.code == identity.ADDRESS_AS_IDENTITY


# ------------------------------------------------- the ordering of the freeze


def test_a_roster_cannot_be_generated_against_a_draft_protocol():
    """Fix the rule, then look. The ordering cannot be reversed by accident."""
    with pytest.raises(protocol_module.ProtocolRefused) as caught:
        _roster(protocol=protocol_module.Protocol())
    assert "roster generation" in str(caught.value)


def test_a_frozen_protocol_permits_generation():
    assert _roster(protocol=protocol_module.Protocol().freeze()).entries


def test_the_roster_records_the_protocol_it_was_generated_under():
    assert _roster().body()["protocol_digest"] == FROZEN.digest()


def test_the_roster_records_the_selection_that_produced_it():
    selection = selection_module.select(_catalogue(), _rule())
    assert _roster(selection=selection).body()["selection_digest"] == (
        selection["selection_digest"]
    )


# ------------------------------------------------------------------ sealing


def test_a_fresh_roster_is_not_sealed():
    assert _roster().sealed is False


def test_sealing_records_the_digest():
    roster = _roster()
    assert roster.seal() == roster.digest()
    assert roster.sealed is True


def test_sealing_twice_refuses_rather_than_being_idempotent():
    """Idempotence would be friendlier and wrong.

    A caller sealing twice has lost track of whether the roster in hand is the
    one that was sealed the first time, and that is precisely the confusion a
    seal exists to prevent.
    """
    roster = _roster()
    roster.seal()
    with pytest.raises(roster_module.RosterRefused) as caught:
        roster.seal()
    assert caught.value.code == roster_module.ALREADY_SEALED


def test_sealing_does_not_change_what_the_roster_says():
    roster = _roster()
    before = roster.digest()
    assert roster.seal() == before
    assert roster.digest() == before


def test_the_seal_verifies_against_a_recomputed_digest():
    roster = _roster()
    roster.seal()
    assert roster.verify_seal()["intact"] is True


def test_the_seal_notices_an_entry_altered_after_sealing():
    roster = _roster()
    roster.seal()
    altered = list(roster.entries)
    altered[0] = roster_module.RosterEntry(
        **{**altered[0].as_dict(), "source_rank": 999}
    )
    roster.entries = tuple(altered)
    assert roster.verify_seal()["intact"] is False


def test_an_unsealed_roster_refuses_what_requires_a_seal():
    roster = _roster()
    with pytest.raises(roster_module.RosterRefused) as caught:
        roster.require_sealed("measurement")
    assert caught.value.code == roster_module.NOT_SEALED
    assert "moving cohort" in str(caught.value)


def test_the_roster_digest_depends_on_the_order_of_its_entries():
    """Rank order is part of what was selected, not an incidental arrangement.

    A digest that sorted its entries first would report two different cohorts --
    the top fifty and the same fifty ranked differently -- as one.
    """
    roster = _roster()
    before = roster.digest()
    roster.entries = tuple(reversed(roster.entries))
    assert roster.digest() != before


def test_two_different_rosters_seal_to_different_digests():
    a = _roster()
    b = _roster(selection=selection_module.select(_catalogue(), _rule(partition_index=1)))
    assert a.seal() != b.seal()


# ---------------------------------------------- execution evidence is separate


def test_the_live_address_is_not_part_of_the_roster():
    """Asked of the entries, which is where the question actually lives.

    A scan of the whole body finds these names in the very lists that declare
    them excluded -- the roster's own, and the exclusion proof's. What must hold
    is that no *entry* carries one.
    """
    roster = _roster()
    for entry in roster.entries:
        assert roster_module.FORBIDDEN_ROSTER_FIELDS.isdisjoint(entry.as_dict())
    serialized = str([entry.as_dict() for entry in roster.entries])
    assert "canonical_address" not in serialized
    assert "renamed" not in serialized


def test_execution_evidence_is_recorded_against_the_roster_by_digest():
    roster = _roster()
    seal = roster.seal()
    evidence = roster.execution_evidence(
        [
            {
                "host_uuid": roster.entries[0].host_uuid,
                "canonical_address": "new-org/new-name",
                "renamed": True,
                "identity_verified": True,
            }
        ]
    )
    assert evidence["roster_digest"] == seal
    assert evidence["is_part_of_the_roster"] is False
    assert evidence["observations"][0]["renamed"] is True


def test_execution_evidence_does_not_alter_the_roster():
    """The cohort must be the same document before and after the study runs."""
    roster = _roster()
    seal = roster.seal()
    roster.execution_evidence(
        [
            {
                "host_uuid": roster.entries[0].host_uuid,
                "canonical_address": "new/name",
                "renamed": True,
                "identity_verified": True,
            }
        ]
    )
    assert roster.verify_seal()["intact"] is True
    assert roster.digest() == seal


def test_evidence_about_a_root_outside_the_roster_refuses():
    roster = _roster()
    roster.seal()
    with pytest.raises(roster_module.RosterRefused):
        roster.execution_evidence(
            [{"host_uuid": "7654321", "canonical_address": "a/b", "renamed": False}]
        )


def test_execution_evidence_requires_a_sealed_roster():
    roster = _roster()
    with pytest.raises(roster_module.RosterRefused) as caught:
        roster.execution_evidence([])
    assert caught.value.code == roster_module.NOT_SEALED


def test_the_receipt_says_why_the_live_address_lives_elsewhere():
    assert "not a cohort" in _roster().receipt()["why_no_live_address_here"]
