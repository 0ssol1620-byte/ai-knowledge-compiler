"""V2R4_ALLOWED_DELTA_V1 -- the seventeen red controls, and the green one.

The V2R4 protocol claimed its attestation would record "the V2R3R1 -> V2R4
scientific projection is IDENTICAL". That was false: running the existing
checker against the pair refuses, first on `/cohort/floor_is_not_lowered` -- a
field V2R4 added precisely to say the floor did NOT move.

`v2r3r1_semantics.py` was built for a carry-forward, where the SAME UNSCORED 300
pairs crossed the boundary and exact equality was both true and required. It is
PRESERVED UNTOUCHED, and nothing in this file edits it. What is proved here is
the weaker, true statement -- the scientific core is byte-identical and every
remaining difference is predeclared -- and, more importantly, that the proof can
FAIL in each of the seventeen directions the founder's ruling names.

`test_green_the_exact_intended_transition_passes` comes first so the seventeen
below are not vacuous, and it asserts the machine-readable delta list the
attestation records.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import v2r4_semantics_delta as delta  # noqa: E402

CORE_I6 = "INVARIANT_6_ambiguous_identity_stays_unresolved"
CORE_I4 = "INVARIANT_4_changed_facet_resolves_typed_or_failclosed"
CORE_I1 = "INVARIANT_1_identity_decisions_unchanged"


@pytest.fixture(scope="module")
def successor_body() -> dict[str, Any]:
    return delta.load(delta.SUCCESSOR)


@pytest.fixture
def mutated(tmp_path, successor_body):
    """Write a mutated successor and prove against the real parent."""

    def run(mutate) -> dict[str, Any]:
        body = copy.deepcopy(successor_body)
        mutate(body)
        path = tmp_path / "mutated.yaml"
        path.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
        return delta.prove_allowed_delta(delta.PARENT, path)

    return run


# ---------------------------------------------------------------------------
# the green control, first


def test_green_the_exact_intended_transition_passes():
    body = delta.prove_allowed_delta()
    assert body["held"] is True
    assert body["verdict"] == delta.VERDICT_HELD
    assert body["verdict"] != "IDENTICAL"
    assert body["core_breaches"] == []


def test_green_every_accepted_delta_is_listed_with_its_declaration():
    """A machine-readable list, not a count. The attestation records this."""
    body = delta.prove_allowed_delta()
    assert body["accepted_delta_count"] == len(body["accepted_deltas"])
    for row in body["accepted_deltas"]:
        assert row["path"].startswith("/")
        assert row["declared_at"].startswith("/")
        assert row["path"].startswith(row["declared_at"])
        assert row["category"] in delta.PERMITTED_CATEGORIES
    assert set(body["by_category"]) <= delta.PERMITTED_CATEGORIES


def test_green_the_pass_rule_lost_nothing_and_renamed_one_clause():
    body = delta.prove_allowed_delta()
    assert body["pass_rule"]["nothing_removed"] is True
    assert body["pass_rule"]["compared_as"].endswith("never positionally")
    renamed = body["pass_rule"]["renamed"]
    assert len(renamed) == 1
    assert renamed[0]["from"] == "all eight invariants MET"
    assert "eight wrong names" in renamed[0]["why"]


def test_green_the_old_checker_is_untouched_and_still_refuses_this_pair():
    """The evidence for the carry-forward decision keeps its behaviour.

    If this ever passes, `v2r3r1_semantics.py` has been weakened to make V2R4
    fit -- which would destroy what it was built to detect and make a false
    claim true by fiat.
    """
    import v2r3r1_semantics as old

    with pytest.raises(old.SemanticsDiffer):
        old.prove_semantic_equivalence(delta.PARENT, delta.SUCCESSOR)


# ---------------------------------------------------------------------------
# 1-2. the floors


def test_red_01_pair_floor_lowered_refuses(mutated):
    with pytest.raises(delta.DeltaRefused, match="scientific core is not preserved"):
        mutated(lambda b: b["cohort_sufficiency"].__setitem__("minimum_admitted_pairs", 199))


def test_red_02_families_required_lowered_refuses(mutated):
    with pytest.raises(delta.DeltaRefused, match="scientific core is not preserved"):
        mutated(lambda b: b["cohort_sufficiency"].__setitem__("minimum_families", 2))


# ---------------------------------------------------------------------------
# 3-7. INVARIANT_6's machinery


def test_red_03_i6_zero_tolerance_changed_refuses(mutated):
    with pytest.raises(delta.DeltaRefused, match="scientific core is not preserved"):
        mutated(
            lambda b: b["invariants"][CORE_I6].__setitem__(
                "zero_tolerance", "a small number of violations is tolerated"
            )
        )


def test_red_04_an_effective_disposition_obligation_deleted_refuses(mutated):
    """Deleting a row is a change to the state machine, not a tidy-up."""

    def drop_row(body):
        body["effective_identity_disposition"]["rows"].pop("A")

    with pytest.raises(delta.DeltaRefused, match="scientific core is not preserved"):
        mutated(drop_row)


def test_red_05_quarantined_new_semantics_changed_refuses(mutated):
    """Row B is the row V2R2 died of. QUARANTINED NEW is EFFECTIVE_UNRESOLVED."""

    def flip(body):
        body["effective_identity_disposition"]["rows"]["B"]["effective"] = "EFFECTIVE_NEW"

    with pytest.raises(delta.DeltaRefused, match="scientific core is not preserved"):
        mutated(flip)


def test_red_06_unit_added_allowed_on_effective_unresolved_refuses(mutated):
    """The exact contradiction that made V2R2's instrument unsatisfiable."""

    def allow(body):
        row = body["effective_identity_disposition"]["rows"]["B"]
        row["forbids"] = []
        row["requires"] = ["unit_added"]

    with pytest.raises(delta.DeltaRefused, match="scientific core is not preserved"):
        mutated(allow)


def test_red_07_identity_unresolved_visibility_removed_refuses(mutated):
    def strip(body):
        for row in body["effective_identity_disposition"]["rows"].values():
            if "identity_unresolved" in (row.get("requires") or []):
                row["requires"] = [
                    item for item in row["requires"] if item != "identity_unresolved"
                ]

    with pytest.raises(delta.DeltaRefused, match="scientific core is not preserved"):
        mutated(strip)


# ---------------------------------------------------------------------------
# 8-13. the other preserved semantics


def test_red_08_ignored_facet_policy_changed_refuses(mutated):
    with pytest.raises(delta.DeltaRefused, match="scientific core is not preserved"):
        mutated(
            lambda b: b["predeclared_ignored_facets"].__setitem__(
                "rule", "a facet may be ignored when the data is empty on both sides"
            )
        )


def test_red_09_invariant_4_population_altered_refuses(mutated):
    with pytest.raises(delta.DeltaRefused, match="scientific core is not preserved"):
        mutated(
            lambda b: b["invariants"][CORE_I4].__setitem__(
                "population", "every facet observation, changed or not"
            )
        )


def test_red_10_the_pass_rule_altered_refuses(mutated):
    """A clause dropped from the acceptance rule, which no category licenses."""

    def drop(body):
        body["pass_rule"]["requires_all_of"] = [
            clause
            for clause in body["pass_rule"]["requires_all_of"]
            if clause != "no invariant UNPROVEN"
        ]

    with pytest.raises(delta.DeltaRefused, match="pass rule dropped"):
        mutated(drop)


def test_red_10b_a_preserved_pass_rule_clause_altered_refuses(mutated):
    with pytest.raises(delta.DeltaRefused, match="scientific core is not preserved"):
        mutated(
            lambda b: b["pass_rule"].__setitem__(
                "no_threshold", "a small violation rate is within tolerance"
            )
        )


def test_red_11_the_vacuity_rule_altered_refuses(mutated):
    with pytest.raises(delta.DeltaRefused, match="scientific core is not preserved"):
        mutated(
            lambda b: b["vacuity_rule"].__setitem__(
                "statement", "a closure over zero pairs PASSES as trivially clean"
            )
        )


def test_red_12_expectation_oracle_semantics_changed_refuses(mutated):
    with pytest.raises(delta.DeltaRefused, match="scientific core is not preserved"):
        mutated(
            lambda b: b["expectation_oracle"].__setitem__(
                "forbidden_imports", []
            )
        )


def test_red_13_an_unchanged_invariant_body_altered_refuses(mutated):
    with pytest.raises(delta.DeltaRefused, match="scientific core is not preserved"):
        mutated(
            lambda b: b["invariants"][CORE_I1].__setitem__(
                "met_when", "violations <= 2"
            )
        )


# ---------------------------------------------------------------------------
# 14-16. the contract's own shape


def test_red_14_an_undeclared_scientific_block_refuses(mutated):
    """A block nobody classified could carry any rule at all."""
    with pytest.raises(delta.DeltaRefused, match="differs where nothing declared it may"):
        mutated(
            lambda b: b.__setitem__(
                "a_new_scientific_block", {"rule": "something nobody reviewed"}
            )
        )


def test_red_15_removing_a_declaration_while_leaving_the_delta_refuses(monkeypatch):
    """Control 15. The delta becomes uncovered the moment its licence is gone."""
    remaining = tuple(
        row for row in delta.ALLOWED_DELTAS if row.path != ("exclusion_policy",)
    )
    assert len(remaining) == len(delta.ALLOWED_DELTAS) - 1
    monkeypatch.setattr(delta, "ALLOWED_DELTAS", remaining)
    with pytest.raises(delta.DeltaRefused, match="differs where nothing declared it may"):
        delta.prove_allowed_delta()


def test_red_16_an_unneeded_declaration_refuses(monkeypatch):
    """Control 16. Dead permission is what a later edit slips through."""
    spare = delta.AllowedDelta(
        ("a_block_that_does_not_differ",), "administrative", "kept just in case"
    )
    monkeypatch.setattr(delta, "ALLOWED_DELTAS", (*delta.ALLOWED_DELTAS, spare))
    with pytest.raises(delta.DeltaRefused, match="covering no actual difference"):
        delta.prove_allowed_delta()


def test_red_16b_a_wildcard_over_the_core_refuses_at_declaration_time(monkeypatch):
    """`/invariants/*` never reaches a protocol -- it fails on the declaration."""
    wildcard = delta.AllowedDelta(("invariants",), "i8_hygiene", "everything, please")
    monkeypatch.setattr(delta, "ALLOWED_DELTAS", (*delta.ALLOWED_DELTAS, wildcard))
    with pytest.raises(delta.DeltaRefused, match="reaches into the scientific core"):
        delta._require_no_delta_reaches_the_core()


@pytest.mark.parametrize(
    "block", ["cohort_sufficiency", "vacuity_rule", "expectation_oracle"]
)
def test_red_16c_no_broad_wildcard_over_any_core_block_is_accepted(monkeypatch, block):
    wildcard = delta.AllowedDelta((block,), "administrative", "broad")
    monkeypatch.setattr(delta, "ALLOWED_DELTAS", (*delta.ALLOWED_DELTAS, wildcard))
    with pytest.raises(delta.DeltaRefused, match="reaches into the scientific core"):
        delta._require_no_delta_reaches_the_core()


def test_red_16d_a_category_nobody_granted_refuses(monkeypatch):
    rogue = delta.AllowedDelta(("release",), "whatever_seems_fine", "unreviewed")
    monkeypatch.setattr(delta, "ALLOWED_DELTAS", (*delta.ALLOWED_DELTAS, rogue))
    with pytest.raises(delta.DeltaRefused, match="claims category"):
        delta._require_no_delta_reaches_the_core()


# ---------------------------------------------------------------------------
# 17. the sentence the V2R3 episode turned on


def test_red_17_weakening_no_post_freeze_change_refuses(mutated):
    def weaken(body):
        body["freeze"]["no_post_freeze_change"]["rule"] = (
            "after rung 4 the protocol may be amended with a recorded reason"
        )

    with pytest.raises(delta.DeltaRefused, match="scientific core is not preserved"):
        mutated(weaken)


# ---------------------------------------------------------------------------
# the rename machinery, in both directions


def test_a_declared_rename_that_did_not_happen_refuses(monkeypatch):
    """Dead permission, in the one place it would license a real weakening."""
    monkeypatch.setattr(
        delta,
        "CLAUSE_RENAMES",
        (*delta.CLAUSE_RENAMES, ("a clause nobody wrote", "nor this one", "why")),
    )
    with pytest.raises(delta.DeltaRefused, match="renames that did not happen"):
        delta.prove_allowed_delta()


def test_without_the_declared_rename_the_transition_refuses(monkeypatch):
    """The rename is load-bearing: strip it and the clause reads as removed."""
    monkeypatch.setattr(delta, "CLAUSE_RENAMES", ())
    with pytest.raises(delta.DeltaRefused, match="pass rule dropped"):
        delta.prove_allowed_delta()


# ---------------------------------------------------------------------------
# structure


def test_the_core_and_the_declarations_are_disjoint_as_shipped():
    delta._require_no_delta_reaches_the_core()


def test_the_pass_rule_is_compared_as_a_set_not_positionally(mutated):
    """Reordering clauses is not a change; the contract must not report one."""

    def reorder(body):
        body["pass_rule"]["requires_all_of"] = list(
            reversed(body["pass_rule"]["requires_all_of"])
        )

    assert mutated(reorder)["held"] is True


def test_an_absent_protocol_refuses(tmp_path):
    with pytest.raises(delta.DeltaRefused, match="nothing to compare"):
        delta.prove_allowed_delta(delta.PARENT, tmp_path / "never-written.yaml")


def test_main_exits_zero_on_the_real_pair(capsys):
    assert delta.main([]) == 0
    assert delta.VERDICT_HELD in capsys.readouterr().out


def test_main_exits_non_zero_and_says_why(tmp_path, capsys, successor_body):
    body = copy.deepcopy(successor_body)
    body["vacuity_rule"]["statement"] = "zero pairs is a PASS"
    path = tmp_path / "mutated.yaml"
    path.write_text(yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    assert delta.main(["--successor", str(path)]) == 4
    out = capsys.readouterr().out
    assert delta.VERDICT_REFUSED in out
    assert "vacuity_rule" in out


def test_main_writes_nothing_unless_asked(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        delta, "write_immutable", lambda stem, *a, **k: calls.append(stem) or {"receipt": "x"}
    )
    delta.main([])
    assert calls == []
