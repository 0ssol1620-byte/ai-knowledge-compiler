"""The eight red controls the founder's ruling requires, plus the anchor's own.

The gate under test answers one question: do the thing that ACCEPTS and the
thing that GRADES talk about the same eight objects? INC-V2-067 is what happens
when nobody asks -- a frozen pass rule requiring eight invariants, an instrument
aggregating one, and a 300-pair corpus spent on a study that could never have
produced the PASS its own rule described.

The controls, numbered as the ruling numbers them:

    1. remove one scorer invariant        -> REFUSE
    2. add an undeclared scorer invariant -> REFUSE
    3. rename one protocol invariant      -> REFUSE
    4. receipt omits one invariant        -> CONTRACT_BROKEN
    5. receipt adds one invariant         -> CONTRACT_BROKEN
    6. an invariant exercises zero observations -> UNPROVEN
    7. one invariant VIOLATED             -> overall FAIL
    8. all eight MET                      -> overall PASS

`test_the_v2r3r1_receipt_on_disk_is_refused` is the one that matters most: the
real artefact that spent the corpus, run through this gate, must be refused by
it. A gate that cannot catch the defect it was written for is decoration.
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import invariant_domain as dom  # noqa: E402

CANON = dom.CANONICAL_INVARIANTS


def _grade_over(names: tuple[str, ...]) -> Any:
    """A stand-in aggregation that emits exactly `names`."""

    def grade(**_inputs: Any) -> dict[str, Any]:
        return {
            "overall": dom.VACUOUS_FAIL,
            "pairs_resolved": 0,
            "invariants": {
                name: {"verdict": dom.UNPROVEN, "exercising_observations": 0} for name in names
            },
        }

    return grade


def _v1_graded_domain() -> tuple[str, ...]:
    """V1's grading domain, obtained by executing `grade()` on a null population.

    The verdicts that come back are meaningless -- every population is empty --
    and are discarded. Only the emitted KEYS are read, because a constant beside
    the function proves nothing about what the function puts in its output.
    """
    import identity_change_migration_closure as v1

    return dom.graded_invariants(
        v1.grade,
        pairs=[],
        fold={
            "violations": [],
            "observations": 0,
            "lossiness_witnesses": 0,
            "per_class": {},
        },
        independence={
            "violations": [],
            "observations": 0,
            "modules_inspected": [],
            "signature": "",
        },
        mapping={"violations": [], "observations": 0, "combinations_evaluated": 0},
        fixtures={
            "held": [],
            "failed": [],
            "drift": {
                "declared_without_a_builder": [],
                "built_without_a_declaration": [],
            },
            "results": {},
        },
        disjointness={"violations": []},
    )


def _receipt(
    names: tuple[str, ...] = CANON,
    *,
    verdicts: dict[str, str] | None = None,
    overall: str | None = None,
    pairs: int = 10,
) -> dict[str, Any]:
    block = {
        name: {
            "verdict": (verdicts or {}).get(name, dom.MET),
            "exercising_observations": 1,
        }
        for name in names
    }
    if overall is None:
        overall = dom.overall_from(block, pairs_resolved=pairs)
    return {
        "overall": overall,
        "pairs_resolved": pairs,
        "invariants": block,
    }


# ---------------------------------------------------------------------------
# the anchor


def test_the_anchor_is_eight_distinct_ids_over_ordinals_one_to_eight():
    dom._require_canonical_is_well_formed()
    assert len(set(CANON)) == 8
    assert dom.ordinals(CANON) == (1, 2, 3, 4, 5, 6, 7, 8)


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param(CANON[:7], id="only seven"),
        pytest.param((*CANON[:7], CANON[0]), id="a repeat, eight entries"),
        pytest.param((*CANON[:7], "INVARIANT_9_invented"), id="ordinal nine"),
        pytest.param((*CANON[:7], "not_an_invariant_id"), id="unparseable id"),
    ],
)
def test_a_malformed_anchor_refuses(monkeypatch, broken):
    """An anchor nobody checks is a ninth place for the defect to live."""
    monkeypatch.setattr(dom, "CANONICAL_INVARIANTS", tuple(broken))
    with pytest.raises(dom.DomainRefused):
        dom._require_canonical_is_well_formed()


# ---------------------------------------------------------------------------
# control 1 and 2 -- the scorer's graded set


def test_the_full_domain_holds_when_all_three_agree():
    """The green direction, so the gate is not always red."""
    held = dom.require_domain_equality(
        declared=CANON, graded=dom.graded_invariants(_grade_over(CANON)), schema=CANON
    )
    assert held["held"] is True
    assert held["ordinals"] == [1, 2, 3, 4, 5, 6, 7, 8]


def test_control_1_a_scorer_missing_one_invariant_refuses():
    graded = dom.graded_invariants(_grade_over(CANON[:7]))
    with pytest.raises(dom.DomainRefused, match="graded set omits"):
        dom.require_domain_equality(declared=CANON, graded=graded, schema=CANON)


def test_control_2_a_scorer_grading_an_undeclared_invariant_refuses():
    graded = dom.graded_invariants(_grade_over((*CANON, "INVARIANT_9_something_new")))
    with pytest.raises(dom.DomainRefused, match="which no invariant set declares"):
        dom.require_domain_equality(declared=CANON, graded=graded, schema=CANON)


def test_control_3_a_renamed_protocol_invariant_refuses():
    renamed = (*CANON[:5], "INVARIANT_6_ambiguity_is_fine_actually", *CANON[6:])
    with pytest.raises(dom.DomainRefused, match="declared set"):
        dom.require_domain_equality(
            declared=tuple(sorted(renamed)), graded=CANON, schema=CANON
        )


def test_eight_wrong_names_fail_even_though_the_count_is_eight():
    """The ruling's own sentence: a count of 8 is NOT sufficient.

    This is the SFI3 freezer's `len(body["endpoints"])` defect stated as a test.
    Two sets of eight can disagree on every member.
    """
    wrong = tuple(sorted(f"INVARIANT_{index}_entirely_different" for index in range(1, 9)))
    assert len(wrong) == 8
    with pytest.raises(dom.DomainRefused):
        dom.require_domain_equality(declared=wrong, graded=CANON, schema=CANON)


def test_a_schema_requiring_a_different_set_refuses():
    with pytest.raises(dom.DomainRefused, match="result schema"):
        dom.require_domain_equality(declared=CANON, graded=CANON, schema=CANON[:7])


def test_the_report_names_which_relationship_broke():
    """Three sets can each differ from the anchor and from each other."""
    with pytest.raises(dom.DomainRefused) as error:
        dom.require_domain_equality(declared=CANON[:7], graded=CANON[1:], schema=CANON)
    text = str(error.value)
    assert "declared and graded disagree" in text
    assert "declared and the result schema disagree" in text


# ---------------------------------------------------------------------------
# the graded domain is EXECUTED, not read


def test_a_scorer_that_declares_eight_and_grades_one_is_caught():
    """INC-V2-067 in one test.

    The module carries a tuple naming all eight. Any check that read the tuple
    would agree with the protocol and report clean. Only the OUTPUT tells the
    truth, which is why `graded_invariants` calls the function.
    """

    class LooksRight:
        DECLARED = CANON  # a constant that says eight

        @staticmethod
        def grade(**_inputs: Any) -> dict[str, Any]:
            return {"invariants": {CANON[5]: {"verdict": dom.MET}}}  # grades one

    assert LooksRight.DECLARED == CANON
    graded = dom.graded_invariants(LooksRight.grade)
    assert graded == (CANON[5],)
    with pytest.raises(dom.DomainRefused, match="graded set omits"):
        dom.require_domain_equality(declared=CANON, graded=graded, schema=CANON)


def test_a_grading_function_that_reports_no_invariants_refuses():
    with pytest.raises(dom.DomainRefused, match="no `invariants` block"):
        dom.graded_invariants(lambda **_: {"overall": "PASS"})


def test_a_grading_function_that_cannot_be_run_refuses_rather_than_passing():
    def explodes(**_inputs: Any) -> dict[str, Any]:
        raise RuntimeError("needs a universe")

    with pytest.raises(dom.DomainRefused, match="could not be executed"):
        dom.graded_invariants(explodes)


# ---------------------------------------------------------------------------
# control 4 and 5 -- the receipt


def test_a_complete_receipt_holds():
    held = dom.require_receipt_domain(_receipt())
    assert held["held"] is True
    assert held["overall"] == dom.PASS
    assert set(held["verdicts"]) == set(CANON)


def test_control_4_a_receipt_omitting_one_invariant_is_contract_broken():
    with pytest.raises(dom.ContractBroken, match="receipt omits"):
        dom.require_receipt_domain(_receipt(CANON[:7]))


def test_control_5_a_receipt_adding_one_invariant_is_contract_broken():
    with pytest.raises(dom.ContractBroken, match="which no invariant set declares"):
        dom.require_receipt_domain(_receipt((*CANON, "INVARIANT_9_extra")))


def test_a_receipt_with_no_overall_verdict_is_contract_broken():
    """Otherwise a reader aggregates the invariants after the outcome is known."""
    body = _receipt()
    body.pop("overall")
    with pytest.raises(dom.ContractBroken, match="interpretation step after the"):
        dom.require_receipt_domain(body)


def test_a_receipt_using_an_invented_verdict_is_contract_broken():
    with pytest.raises(dom.ContractBroken, match="not one of"):
        dom.require_receipt_domain(_receipt(verdicts={CANON[0]: "PROBABLY_FINE"}))


def test_a_receipt_whose_invariant_carries_no_verdict_is_contract_broken():
    body = _receipt()
    body["invariants"][CANON[3]] = {"exercising_observations": 4}
    with pytest.raises(dom.ContractBroken, match="carries no verdict"):
        dom.require_receipt_domain(body)


# ---------------------------------------------------------------------------
# control 6, 7 and 8 -- the pass rule, evaluated by the scorer


def test_control_6_an_unexercised_invariant_yields_unproven_overall():
    body = _receipt(verdicts={CANON[2]: dom.UNPROVEN})
    assert body["overall"] == dom.UNPROVEN
    assert dom.require_receipt_domain(body)["overall"] == dom.UNPROVEN


def test_control_7_one_violated_invariant_yields_overall_fail():
    body = _receipt(verdicts={CANON[6]: dom.VIOLATED})
    assert body["overall"] == dom.FAIL


def test_control_8_all_eight_met_yields_overall_pass():
    assert _receipt()["overall"] == dom.PASS


def test_a_violation_outranks_an_unproven():
    """FAIL is not softened to UNPROVEN by an unexercised neighbour."""
    body = _receipt(verdicts={CANON[0]: dom.VIOLATED, CANON[1]: dom.UNPROVEN})
    assert body["overall"] == dom.FAIL


def test_zero_pairs_is_vacuous_fail_before_any_invariant_is_read():
    block = {name: {"verdict": dom.MET} for name in CANON}
    assert dom.overall_from(block, pairs_resolved=0) == dom.VACUOUS_FAIL


# ---------------------------------------------------------------------------
# the real artefacts


def test_the_v2r3r1_protocol_declares_exactly_the_canonical_eight():
    declared = dom.declared_invariants(
        NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3R1.yaml"
    )
    assert declared == tuple(sorted(CANON))


def test_the_v2r3r1_receipt_on_disk_is_refused():
    """The artefact that spent the corpus, run through the gate written for it.

    It carries `INVARIANT_6_…` and no `overall`. Seven invariants are absent.
    A gate that cannot catch the defect it exists for is decoration, so this is
    checked against the real file rather than a reconstruction of it.
    """
    found = sorted(
        glob.glob(str(NS / "receipts" / "identity-change-migration-closure-v2r3r1--*.json"))
    )
    assert found, "no V2R3R1 measurement receipt on disk"
    body = json.loads(Path(found[-1]).read_text(encoding="utf-8"))
    assert "INVARIANT_6_ambiguous_identity_stays_unresolved" in body
    assert "overall" not in body
    with pytest.raises(dom.ContractBroken):
        dom.require_receipt_domain(body)


def test_the_v1_scorer_grades_all_eight():
    """The architecture the ruling points V2R4 at, verified by executing it.

    V1's `grade()` is called on a null population: the verdicts are meaningless
    and discarded, and only the emitted KEYS are read. If this ever returns
    fewer than eight, V2R4 has no full-closure architecture to build on and the
    ruling's paragraph 6 no longer holds.
    """
    graded = _v1_graded_domain()
    assert graded == tuple(sorted(CANON))


def test_the_v1_scorer_and_the_v2r3r1_protocol_agree_on_the_domain():
    """The pairing V2R4 is built from: V1's grading domain, V2R3's declarations."""
    graded = _v1_graded_domain()
    declared = dom.declared_invariants(
        NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3R1.yaml"
    )
    assert dom.require_domain_equality(declared=declared, graded=graded, schema=CANON)["held"]
