"""Controls for SFIR9 fresh roster selection.

The property being defended is that nothing SFIR7 or SFIR8 observed can reach
the selection. That is easy to promise and hard to prove, so it is checked from
three directions: N is a function only of declared execution-envelope terms, a
catalogue row carrying an observed field refuses the whole selection, and the
roster is stable when observations change and unstable only when the frozen
protocol does.

The partition-before-ordering property gets its own controls, because it is what
answers "you picked the easy repositories". If the ordering ran over the whole
catalogue, the roster would be the top-ranked repositories in the world; running
it inside a salted hash bucket makes the population one nobody could have chosen.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir9_selection as selection  # noqa: E402


def term(name, value, source=selection.EXTERNAL):
    return selection.EnvelopeTerm(
        name=name, value=value, source=source, rationale=f"declared {name}"
    )


def envelope(
    windows=6,
    per_window=4500,
    allowance=540,
    windows_source=selection.EXTERNAL,
    per_window_source=selection.EXTERNAL,
    allowance_source=selection.EXTERNAL,
):
    """Values and their sources are separate parameters on purpose.

    The first version of this helper folded the sources into `**kwargs` under
    the same names as the values, so `envelope(windows=OBSERVATION)` set the
    *value* to a string and left the source external -- and the two controls
    that were supposed to prove the refusal fires never reached it.
    """
    return selection.ExecutionEnvelope(
        permitted_rate_windows=term("permitted_rate_windows", windows, windows_source),
        usable_charge_per_window=term(
            "usable_charge_per_window", per_window, per_window_source
        ),
        per_root_charge_allowance=term(
            "per_root_charge_allowance", allowance, allowance_source
        ),
    )


def rule(**overrides):
    body = dict(
        salt="sfir9-frozen-salt-v1",
        partition_count=8,
        partition_index=0,
        envelope=envelope(),
        spent_host_uuids=frozenset(),
    )
    body.update(overrides)
    return selection.FrozenSelection(**body)


def catalogue(count=4000):
    """Rows carrying only external catalogue metadata."""
    return [
        {
            "host_uuid": str(100000 + i),
            "name_with_owner": f"org{i}/repo{i}",
            "record_id": f"r{i:06d}",
            "source_rank": i % 30,
        }
        for i in range(count)
    ]


# ------------------------------------------------------------ N from the envelope


def test_n_is_the_envelope_divided_by_the_per_root_allowance():
    assert envelope(windows=6, per_window=4500, allowance=540).derive_n() == 50


def test_n_moves_with_every_envelope_term():
    base = envelope().derive_n()
    assert envelope(windows=12).derive_n() == base * 2
    assert envelope(per_window=9000).derive_n() == base * 2
    assert envelope(allowance=1080).derive_n() == base // 2


def test_an_envelope_term_sourced_from_an_observation_is_refused():
    """N must be a function of what the study may spend, never of what it saw."""
    with pytest.raises(selection.SelectionRefused, match="never of what an earlier"):
        selection.require_no_observation_participates(
            envelope(allowance_source=selection.OBSERVATION)
        )


@pytest.mark.parametrize(
    "which,named",
    [
        ("windows_source", "permitted_rate_windows"),
        ("per_window_source", "usable_charge_per_window"),
        ("allowance_source", "per_root_charge_allowance"),
    ],
)
def test_each_term_individually_must_be_external(which, named):
    with pytest.raises(selection.SelectionRefused, match=named):
        selection.require_no_observation_participates(
            envelope(**{which: selection.OBSERVATION})
        )


def test_a_clean_envelope_passes_the_same_check():
    """The refusal must be about the source, not about being checked at all."""
    selection.require_no_observation_participates(envelope())


def test_select_refuses_before_reading_a_single_row_if_a_term_is_observed():
    """The check runs first, so a tainted envelope costs no work."""
    with pytest.raises(selection.SelectionRefused, match="per_root_charge_allowance"):
        selection.select(
            catalogue(10), rule(envelope=envelope(allowance_source=selection.OBSERVATION))
        )


def test_a_non_positive_allowance_refuses_rather_than_dividing():
    with pytest.raises(selection.SelectionRefused, match="not defined"):
        envelope(allowance=0).derive_n()


def test_the_derivation_names_every_term_and_its_source():
    described = envelope().describe()
    assert {t["name"] for t in described["terms"]} == {
        "permitted_rate_windows",
        "usable_charge_per_window",
        "per_root_charge_allowance",
    }
    assert all(t["source"] == selection.EXTERNAL for t in described["terms"])
    assert described["n"] == described["global_charge_budget"] // 540


def test_the_budget_is_denominated_in_provider_charges():
    """SFIR7 bounded logical requests and was billed for network hops."""
    described = envelope().describe()
    assert "charge" in described["formula"]
    assert "790" in described["why_charges_and_not_logical_requests"]


# ---------------------------------------------------- nothing observed gets in


@pytest.mark.parametrize("forbidden", sorted(selection.FORBIDDEN_SELECTION_INPUTS))
def test_a_row_carrying_an_observed_field_refuses_the_whole_selection(forbidden):
    """Refused, not filtered.

    A forbidden field arriving here means something upstream joined study output
    onto the frozen catalogue. Dropping the field would leave that join in place
    for the next caller, who might not be looking.
    """
    rows = catalogue(50)
    rows[7][forbidden] = 1
    with pytest.raises(selection.SelectionRefused, match="joined onto"):
        selection.select(rows, rule())


def test_the_forbidden_list_names_what_the_earlier_studies_produced():
    assert {
        "candidate_count",
        "tree_size",
        "framework",
        "language",
        "rename_status",
        "traversal_difficulty",
        "completion_status",
    } <= selection.FORBIDDEN_SELECTION_INPUTS


def test_a_clean_catalogue_selects_without_complaint():
    result = selection.select(catalogue(), rule())
    assert result["roster"]
    assert result["n"] == 50


# ------------------------------------------------- partition before ordering


def test_the_roster_is_not_simply_the_top_ranked_repositories():
    """The objection this design exists to answer."""
    rows = catalogue()
    globally_top = sorted(rows, key=lambda r: (-r["source_rank"], r["record_id"]))[:50]
    roster = selection.select(rows, rule())["roster"]
    chosen = {entry["host_uuid"] for entry in roster}
    assert chosen != {r["host_uuid"] for r in globally_top}


def test_the_ordering_still_runs_inside_the_partition():
    """Deterministic, and by the catalogue's own external ordinal."""
    rows = catalogue()
    result = selection.select(rows, rule())
    ranks = [entry["source_rank"] for entry in result["roster"]]
    assert ranks == sorted(ranks, reverse=True)


def test_ties_are_broken_by_the_external_record_id():
    rows = catalogue()
    result = selection.select(rows, rule())
    for a, b in zip(result["roster"], result["roster"][1:], strict=False):
        if a["source_rank"] == b["source_rank"]:
            assert a["record_id"] < b["record_id"]


def test_the_partition_is_keyed_on_identity_not_address():
    """A partition that moved on rename would depend on something SFIR7 observed."""
    frozen = rule()
    assert frozen.partition_of("100001") == frozen.partition_of("100001")


def test_a_different_salt_selects_a_different_population():
    rows = catalogue()
    first = selection.select(rows, rule())["roster"]
    second = selection.select(rows, rule(salt="a-different-frozen-salt"))["roster"]
    assert {e["host_uuid"] for e in first} != {e["host_uuid"] for e in second}


def test_the_salt_itself_is_not_published_only_its_digest():
    """The roster is reproducible from the frozen protocol; the salt stays in it."""
    result = selection.select(catalogue(), rule())
    assert "sfir9-frozen-salt-v1" not in str(result)
    assert result["partition"]["salt_digest"].startswith("sha256:")


def test_the_partitions_are_roughly_balanced():
    """A hash that piled everything into one bucket would not be a partition."""
    frozen = rule()
    counts = [0] * frozen.partition_count
    for row in catalogue(8000):
        counts[frozen.partition_of(row["host_uuid"])] += 1
    assert min(counts) > 8000 / frozen.partition_count * 0.7
    assert max(counts) < 8000 / frozen.partition_count * 1.3


def test_rows_outside_the_partition_are_counted_not_silently_dropped():
    result = selection.select(catalogue(), rule())
    assert result["partition"]["rows_outside_partition"] > 0
    assert (
        result["partition"]["rows_outside_partition"] + result["eligible_in_partition"]
        == 4000
    )


# --------------------------------------------------------- spent-root exclusion


def test_a_spent_identity_inside_the_partition_is_excluded():
    frozen = rule()
    inside = [r for r in catalogue() if frozen.admits(r["host_uuid"])]
    spent = {inside[0]["host_uuid"], inside[1]["host_uuid"]}
    result = selection.select(catalogue(), rule(spent_host_uuids=frozenset(spent)))

    assert result["exclusions"]["count"] == 2
    assert set(result["exclusions"]["host_uuids"]) == spent
    assert spent.isdisjoint({e["host_uuid"] for e in result["roster"]})


def test_the_only_exclusion_reason_is_that_they_were_looked_at():
    result = selection.select(catalogue(), rule(spent_host_uuids=frozenset({"100000"})))
    assert result["exclusions"]["reason"] == selection.SPENT
    assert selection.SPENT == "SPENT_DEVELOPMENT_ROOT"
    assert "looked at" in result["exclusions"]["why"]


def test_excluding_a_spent_root_promotes_the_next_eligible_one():
    """The roster stays the declared size rather than shrinking by the exclusion."""
    frozen = rule()
    inside = [r for r in catalogue() if frozen.admits(r["host_uuid"])]
    assert len(inside) > 51
    plain = selection.select(catalogue(), rule())
    top = plain["roster"][0]["host_uuid"]
    reduced = selection.select(catalogue(), rule(spent_host_uuids=frozenset({top})))
    assert len(reduced["roster"]) == len(plain["roster"])
    assert top not in {e["host_uuid"] for e in reduced["roster"]}


def test_a_partition_too_small_for_n_reports_a_short_roster():
    """Reported rather than topped up from outside the partition."""
    result = selection.select(catalogue(60), rule())
    assert result["roster_is_short"] is True
    assert len(result["roster"]) < result["n"]


# ------------------------------------------------------------- reproducibility


def test_selection_is_deterministic():
    rows = catalogue()
    assert selection.select(rows, rule()) == selection.select(list(rows), rule())


def test_selection_does_not_depend_on_the_order_rows_arrive_in():
    rows = catalogue()
    shuffled = list(reversed(rows))
    assert (
        selection.roster_fingerprint(selection.select(rows, rule()))
        == selection.roster_fingerprint(selection.select(shuffled, rule()))
    )


def test_the_roster_fingerprint_depends_on_rank_order():
    result = selection.select(catalogue(), rule())
    reversed_roster = dict(result)
    reversed_roster["roster"] = list(reversed(result["roster"]))
    assert selection.roster_fingerprint(reversed_roster) != selection.roster_fingerprint(
        result
    )


def test_the_selection_digest_changes_with_the_frozen_rule():
    base = rule().digest()
    assert rule(salt="other").digest() != base
    assert rule(partition_index=1).digest() != base
    assert rule(envelope=envelope(windows=12)).digest() != base
    assert rule(spent_host_uuids=frozenset({"1"})).digest() != base


def test_the_selection_digest_is_stable_for_the_same_rule():
    assert rule().digest() == rule().digest()


def test_two_identities_do_not_share_a_partition_by_construction():
    """A partition that ignored the identity would put everything in one bucket.

    Mutation S8 first tried to express this by giving `partition_of` a default
    argument, which every caller overrides and which therefore changed nothing --
    an equivalent mutant, and a reminder that a mutation has to be able to
    produce the defect it is named for. Removing the identity from the hashed
    material does produce it, and this is what notices.
    """
    frozen = rule()
    buckets = {frozen.partition_of(str(100000 + i)) for i in range(200)}
    assert len(buckets) == frozen.partition_count, (
        "every identity landed in the same bucket, so the partition is not a "
        "function of the identity it claims to partition"
    )
