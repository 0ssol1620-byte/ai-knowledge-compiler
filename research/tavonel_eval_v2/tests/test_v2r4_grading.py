"""The V2R4 grading core: eight invariants graded, one verdict produced.

What these tests establish, before any cohort exists:

* the module grades all eight invariants, observed by RUNNING it -- the
  distinction that INC-V2-067 turned on, where a scorer could have carried a
  tuple of eight and aggregated one;
* INVARIANT_6 is graded over five clauses, and (c),(d),(e) can move its verdict;
* the two populations -- V1's per-pair measurement and V2R3's per-pair effective
  surface -- are checked to line up rather than assumed to;
* INVARIANT_8's exclusion set is checked as a DOMAIN, so a universe silent about
  a spent cohort is refused rather than read as clean;
* the pass rule has exactly one implementation, and the scorer applies it.

Driving each invariant red on real documents is the rehearsal's job (the
founder's paragraph 8). These tests are about the aggregation: that it covers
eight, that it can move, and that it refuses what it cannot read.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import invariant_domain as dom  # noqa: E402
import v2r4_grading as g  # noqa: E402

CANON = dom.CANONICAL_INVARIANTS


def _pair(lineage: str, **overrides: Any) -> dict[str, Any]:
    """One V1-shaped per-pair measurement with every population non-empty."""
    row = {
        "lineage_id": lineage,
        "family": "git_docs",
        "matched_pair_count": 4,
        "changed_facet_observations": 3,
        "unresolved_facet_observations": 2,
        "unresolved_without_a_production_fail_closed_behaviour": 0,
        "ambiguity_observations": 1,
        "change_equivalent_observations": 0,
        "legacy_modified_count": 0,
        "new_modified_count": 0,
        "violations": {f"INVARIANT_{n}": [] for n in range(1, 9)},
    }
    row.update(overrides)
    return row


def _extra(lineage: str, **clauses: Any) -> dict[str, Any]:
    entry = {
        "lineage_id": lineage,
        "family": "git_docs",
        "c": {"violations": [], "observations": 5},
        "d": {"violations": [], "observations": 7},
        "e": {"violations": [], "observations": 2},
        "unsettled_identities": 0,
        "census": {},
    }
    entry.update(clauses)
    return entry


def _inputs(pairs: list[dict[str, Any]], extra: list[dict[str, Any]]) -> dict[str, Any]:
    """Null-but-exercised inputs: every other invariant MET, so I6 is visible."""
    body = g.null_grading_inputs()
    body.update(
        {
            "pairs": pairs,
            "extra": extra,
            "fold": {
                "violations": [],
                "observations": 12,
                "lossiness_witnesses": 3,
                "per_class": {},
            },
            "independence": {
                "violations": [],
                "observations": 4,
                "modules_inspected": ["x.py"],
                "signature": "sha256:0",
            },
            "mapping": {"violations": [], "observations": 72, "combinations_evaluated": 72},
        }
    )
    return body


# ---------------------------------------------------------------------------
# the grading domain


def test_the_module_grades_all_eight_observed_by_running_it():
    assert g.graded_domain() == tuple(sorted(CANON))


def test_a_null_population_is_vacuous_fail_not_pass():
    body = g.grade(**g.null_grading_inputs())
    assert body["overall"] == dom.VACUOUS_FAIL
    assert set(body["invariants"]) == set(CANON)


def test_the_result_schema_declares_the_same_eight():
    assert dom.schema_invariants(g.RESULT_INVARIANT_KEYS) == tuple(sorted(CANON))


def test_a_full_result_satisfies_the_receipt_contract():
    """The check INC-V2-067's receipt could not have satisfied."""
    body = g.grade(**_inputs([_pair("a")], [_extra("a")]))
    held = dom.require_receipt_domain(body)
    assert held["held"] is True
    assert set(held["verdicts"]) == set(CANON)


# ---------------------------------------------------------------------------
# INVARIANT_6 over five clauses


def test_all_eight_met_over_an_exercised_population_is_a_pass():
    body = g.grade(**_inputs([_pair("a"), _pair("b")], [_extra("a"), _extra("b")]))
    assert body["overall"] == dom.PASS
    assert body["invariants"][g.INVARIANT_6]["verdict"] == dom.MET


@pytest.mark.parametrize("clause", ["c", "d", "e"])
def test_a_violation_in_any_v2r3_clause_moves_invariant_6_and_the_overall(clause):
    """The clauses V1 did not have must be able to fail the study.

    A clause that is computed and cannot change the verdict is decoration; this
    is the direction that proves (c), (d) and (e) are actually wired into the
    aggregation rather than reported beside it.
    """
    entry = _extra("a", **{clause: {"violations": [{"why": "broke"}], "observations": 3}})
    body = g.grade(**_inputs([_pair("a")], [entry]))
    assert body["invariants"][g.INVARIANT_6]["verdict"] == dom.VIOLATED
    assert body["overall"] == dom.FAIL
    assert [v["clause"] for v in body["invariants"][g.INVARIANT_6]["violations"]] == [clause]


def test_a_violation_in_clause_a_or_b_still_moves_invariant_6():
    """V1's half is not lost by composing V2R3's onto it."""
    pair = _pair("a", violations={**_pair("a")["violations"], "INVARIANT_6": [{"why": "ab"}]})
    body = g.grade(**_inputs([pair], [_extra("a")]))
    assert body["invariants"][g.INVARIANT_6]["verdict"] == dom.VIOLATED


def test_each_clause_denominator_is_reported_apart():
    """A reader can see which clauses carried the power."""
    block = g.grade(**_inputs([_pair("a")], [_extra("a")]))["invariants"][g.INVARIANT_6]
    assert block["clause_observations"] == {"a_b": 1, "c": 5, "d": 7, "e": 2}
    assert block["exercising_observations"] == 15
    assert block["clauses_graded"] == ["a", "b", "c", "d", "e"]


def test_invariant_6_with_no_observations_anywhere_is_unproven_not_met():
    pair = _pair("a", ambiguity_observations=0)
    entry = _extra(
        "a",
        c={"violations": [], "observations": 0},
        d={"violations": [], "observations": 0},
        e={"violations": [], "observations": 0},
    )
    body = g.grade(**_inputs([pair], [entry]))
    assert body["invariants"][g.INVARIANT_6]["verdict"] == dom.UNPROVEN
    assert body["overall"] == dom.UNPROVEN


# ---------------------------------------------------------------------------
# the two populations must line up


def test_a_pair_with_no_effective_surface_entry_refuses():
    with pytest.raises(g.GradingRefused, match="would be graded over a different"):
        g.grade(**_inputs([_pair("a"), _pair("b")], [_extra("a")]))


def test_misaligned_rows_refuse_rather_than_grading_the_wrong_pair():
    """Same length, different order. A count would not catch this."""
    with pytest.raises(g.GradingRefused, match="was measured against"):
        g.grade(**_inputs([_pair("a"), _pair("b")], [_extra("b"), _extra("a")]))


# ---------------------------------------------------------------------------
# INVARIANT_8's exclusion domain


def _proofs(**overrides: Any) -> dict[str, Any]:
    proved = {key: {"holds": True, "overlap": []} for key in g.REQUIRED_DISJOINTNESS}
    proved.update(overrides)
    return proved


def test_the_declared_exclusion_set_covers_every_spent_cohort():
    """The founder's paragraph 9 list, as a set the code carries."""
    assert "from_v2r3r1_universe" in g.REQUIRED_DISJOINTNESS
    assert "from_vbc1_burned_material" in g.REQUIRED_DISJOINTNESS
    assert len(set(g.REQUIRED_DISJOINTNESS)) == len(g.REQUIRED_DISJOINTNESS)


def test_every_declared_population_is_already_spent_when_v2r4_acquires():
    """INVARIANT_8 excludes SPENT material, so every entry must already exist.

    An earlier draft carried `from_sfi3_material`, meaning every lineage id in
    SFI3's frozen acquisition. That receipt cannot exist when V2R4 needs it --
    the order is V2R4 PASS -> SFI3 acquisition -> SFI3 PASS -> four-link -> GPU
    -- so the requirement was circular and neither study could start.
    """
    assert "from_sfi3_material" not in g.REQUIRED_DISJOINTNESS
    assert not [key for key in g.REQUIRED_DISJOINTNESS if "sfi3" in key]


def test_sfi3_separation_is_documented_as_a_reservation_not_an_invariant():
    """The separation did not go away; it moved to where it can be proved.

    Container reservation happens before V2R4 rung 0, on root identity metadata,
    and needs no future artifact. See `tools/sfi3_root_reservation.py`.
    """
    assert "SFI3_ROOT_RESERVATION_V1" in g.SFI3_SEPARATION_IS_A_RESERVATION_NOT_AN_INVARIANT
    assert "never by INVARIANT_8" in g.SFI3_SEPARATION_IS_A_RESERVATION_NOT_AN_INVARIANT


def test_the_protocol_declares_exactly_what_the_scorer_enforces():
    """The third leg of the exclusion domain.

    A protocol can name a population the code never subtracts, and a reader
    checking the protocol would find the rule stated and never learn it was not
    executed. That is INC-V2-067's shape pointed at exclusions.
    """
    held = g.require_exclusion_domain()
    assert held["equal"] is True
    assert held["declared"] == held["enforced"] == sorted(g.REQUIRED_DISJOINTNESS)
    assert "never a count" in held["compared"]


def test_a_population_declared_in_prose_but_never_enforced_refuses(tmp_path):
    protocol = tmp_path / "p.yaml"
    protocol.write_text(
        yaml.safe_dump(
            {
                "invariants": {
                    g.INVARIANT_8: {
                        "the_declared_populations": dict.fromkeys(
                            [*g.REQUIRED_DISJOINTNESS, "from_somewhere_nobody_subtracts"], "x"
                        )
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(g.GradingRefused, match="declared but never enforced"):
        g.require_exclusion_domain(protocol)


def test_a_population_enforced_but_not_declared_refuses(tmp_path):
    protocol = tmp_path / "p.yaml"
    protocol.write_text(
        yaml.safe_dump(
            {
                "invariants": {
                    g.INVARIANT_8: {
                        "the_declared_populations": dict.fromkeys(
                            list(g.REQUIRED_DISJOINTNESS)[:-1], "x"
                        )
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(g.GradingRefused, match="enforced but not declared"):
        g.require_exclusion_domain(protocol)


def test_seven_wrong_names_do_not_pass_a_count(tmp_path):
    """Two sets of seven can disagree on every member."""
    protocol = tmp_path / "p.yaml"
    protocol.write_text(
        yaml.safe_dump(
            {
                "invariants": {
                    g.INVARIANT_8: {
                        "the_declared_populations": {
                            f"from_population_{n}": "x" for n in range(7)
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert len(g.REQUIRED_DISJOINTNESS) == 7
    with pytest.raises(g.GradingRefused):
        g.require_exclusion_domain(protocol)


def test_a_protocol_naming_no_populations_refuses(tmp_path):
    protocol = tmp_path / "p.yaml"
    protocol.write_text(yaml.safe_dump({"invariants": {}}), encoding="utf-8")
    with pytest.raises(g.GradingRefused, match="is a sentence, not a rule"):
        g.require_exclusion_domain(protocol)


def test_an_absent_protocol_refuses(tmp_path):
    with pytest.raises(g.GradingRefused, match="nothing declares an exclusion set"):
        g.require_exclusion_domain(tmp_path / "never-written.yaml")


def test_a_complete_set_of_proofs_holds():
    body = g.disjointness_from(_proofs())
    assert body["violations"] == []
    assert body["domain"]["equal"] is True


def test_a_universe_silent_about_a_spent_cohort_refuses():
    """Silence is not disjointness.

    A universe proving seven of eight and reporting `holds: true` for each is
    not disjoint from the eighth -- it never looked. That reads as clean to any
    check that only conjoins what is present.
    """
    proofs = _proofs()
    proofs.pop("from_v2r3r1_universe")
    with pytest.raises(g.GradingRefused, match="never proved:"):
        g.disjointness_from(proofs)


def test_a_universe_proving_an_undeclared_cohort_refuses():
    with pytest.raises(g.GradingRefused, match="proved but not declared"):
        g.disjointness_from(_proofs(from_somewhere_else={"holds": True, "overlap": []}))


def test_an_overlap_with_a_spent_cohort_fails_invariant_8():
    proofs = _proofs(from_v2r3r1_universe={"holds": False, "overlap": ["git:x:y.md"]})
    disjointness = g.disjointness_from(proofs)
    body = g.grade(**{**_inputs([_pair("a")], [_extra("a")]), "disjointness": disjointness})
    assert body["invariants"][g.INVARIANT_8]["verdict"] == dom.VIOLATED
    assert body["overall"] == dom.FAIL


def test_a_holds_false_with_an_empty_overlap_still_fails():
    """`holds: false` is refused on its own; it is not softened by an empty list."""
    disjointness = g.disjointness_from(
        _proofs(from_vbc1_burned_material={"holds": False, "overlap": []})
    )
    assert disjointness["violations"]


# ---------------------------------------------------------------------------
# the pass rule has one implementation


def test_the_overall_comes_from_invariant_domain_not_a_second_copy():
    body = g.grade(**_inputs([_pair("a")], [_extra("a")]))
    assert body["overall"] == dom.overall_from(
        body["invariants"], pairs_resolved=body["pairs_resolved"]
    )


def test_one_violated_invariant_outranks_an_unproven_neighbour():
    pair = _pair("a", violations={**_pair("a")["violations"], "INVARIANT_1": [{"why": "x"}]})
    body = g.grade(**{**_inputs([pair], [_extra("a")]), "mapping": {
        "violations": [], "observations": 0, "combinations_evaluated": 0
    }})
    assert body["invariants"][CANON[0]]["verdict"] == dom.VIOLATED
    assert body["overall"] == dom.FAIL


def test_the_domain_gate_refuses_while_the_v2r4_protocol_does_not_exist():
    """Honest about the state: there is no V2R4 protocol yet, so nothing declares.

    This test is expected to change to a green assertion the moment the protocol
    is written; until then it pins that the gate reports absence rather than
    defaulting to agreement.
    """
    protocol = NS / "protocols" / f"{g.PROTOCOL_ID}.yaml"
    if protocol.is_file():
        assert g.require_domain()["held"] is True
    else:
        with pytest.raises(dom.DomainRefused, match="does not exist"):
            g.require_domain()
