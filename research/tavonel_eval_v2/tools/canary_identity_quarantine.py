#!/usr/bin/env python3
"""Rung 4 of the INC-V2-047 quarantine ladder: the canary.

`identity_quarantine_differential` measures what the repair does to the frozen
development universe. This tool asks the next question, the one the
`canary_identity_change` model asks about the INC-V2-037 switch: **is the
difference the shape the adversarial controls said it would be?**

The predictions are not restated here. They are computed from
`tests/test_identity_quarantine.py::CONTROLS` -- the same table the controls run
from -- so a control that is edited moves this gate with it. A canary whose
expectations are a hand-written copy of the controls' expectations gates on
nothing but the author's memory of them.

**Every check carries the class of evidence it is.** The model separates
tautological checks from real ones and refuses to count the tautological ones;
this one needs a third and a fourth label, because two of its checks are neither
tautological nor prospective:

``prospective``
    A property measured over the frozen development universe against a
    prediction the controls made independently of the corpus. The only class
    that counts.
``structural``
    A correspondence between a declaration and an implementation -- every
    declared control has a test and a red test. Real, and about the battery
    rather than about the repair.
``retrospective-development-fixture``
    The nine INVARIANT_6 cases of IDENTITY_CHANGE_MIGRATION_CLOSURE_V1. The
    repair was written after seeing them, so their closure is a development
    regression and can certify nothing prospectively. INC-V2-045's ruling is
    what this label exists to obey: **it is reported and never counted.**
    V1's FAIL is permanent and is not rescored anywhere below.
``tautological``
    True by construction. Reported because a reader is entitled to see the
    contract's own claim checked, and labelled so nobody counts it as
    independent evidence.

**There is no rate threshold and there will not be one here.** The share of
units identical under both pins is reported with its denominator and gated by
nothing. No threshold in this repository is calibrated, and inventing one so the
canary goes green would present an uncalibrated number as a measured bar.

**Nothing here flips `QUARANTINE_UNSETTLED_IDENTITY_DEFAULT`.** That is rung 5.
The observed value is recorded as an observation of the tree; both arms of every
measurement pass the pin explicitly.

Usage::

    python tools/canary_identity_quarantine.py
    python tools/canary_identity_quarantine.py --limit 40
    python tools/canary_identity_quarantine.py --write-receipt
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir", "tests"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))
ROOT = NS.parents[1]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

import identity_quarantine_differential as differential  # noqa: E402
import test_identity_quarantine as controls  # noqa: E402
from evidence import write_immutable  # noqa: E402

STEM = "identity-quarantine-canary"
SCHEMA = "tavonel.v2.canary_identity_quarantine.v1"
OUT_DIR = NS / "artifacts" / "development" / "identity_quarantine"

PROSPECTIVE = "prospective"
STRUCTURAL = "structural"
RETROSPECTIVE = "retrospective-development-fixture"
TAUTOLOGICAL = "tautological"


def predictions_from_controls() -> dict[str, Any]:
    """What the control battery says the corpus difference must look like.

    Read off `CONTROLS` and the module's own test functions rather than written
    down again.
    """
    declared = [name for name, _requirement, _mutation in controls.CONTROLS]
    missing_tests = [name for name in declared if not hasattr(controls, f"test_{name}")]
    missing_reds = [
        name for name in declared if not hasattr(controls, f"test_{name}__can_come_back_red")
    ]
    unknown_mutations = sorted(
        {
            mutation
            for _name, _requirement, mutation in controls.CONTROLS
            if mutation not in controls.RED_MUTATIONS
        }
    )
    return {
        "controls_total": len(controls.CONTROLS),
        "controls": declared,
        "red_mutations_used": sorted({mutation for _n, _r, mutation in controls.CONTROLS}),
        "controls_without_a_test": missing_tests,
        "controls_without_a_red_test": missing_reds,
        "controls_with_an_undeclared_red_mutation": unknown_mutations,
        # Controls 3-6 assert that a settled decision survives the repair. On a
        # corpus that means the definite vocabulary must still be spoken under
        # pin ON -- an over-quarantine would collapse it.
        "predicts_the_definite_vocabulary_survives": True,
        # Controls 1, 2, 7 and 10 all assert the same negative: no unit is both
        # unsettled and definitely classified.
        "predicts_no_unsettled_unit_is_definitely_classified": True,
        # Control 10's second half.
        "predicts_no_unresolved_unit_seeds_a_recompilation": True,
        # The nine V1 cases, as DEVELOPMENT fixtures. Named so the check below
        # can compare sets rather than counts; a count would pass on nine
        # different cases.
        "development_fixture_cases": [
            {"lineage_id": lineage, "logical_id": logical}
            for lineage, logical in controls.V1_INVARIANT_6_CASES
        ],
    }


def gate(report: dict[str, Any], predicted: dict[str, Any]) -> dict[str, Any]:
    properties = report["properties"]
    totals = report["totals"]
    kinds_off = totals["kind_counts_pin_off"]
    kinds_on = totals["kind_counts_pin_on"]
    reasons_on = totals["quarantine_reason_counts_pin_on"]
    membership = totals["quarantine_membership_by_clause"]

    definite = sorted(differential.DEFINITE_KINDS & set(kinds_off))
    collapsed = [kind for kind in definite if kinds_on.get(kind, 0) == 0]

    observed_cases = {
        (row["lineage_id"], row["logical_id"])
        for row in report["reported_not_gated"]["unit_removed_withheld_and_stated_unresolved"]
    }
    fixture_cases = {
        (row["lineage_id"], row["logical_id"]) for row in predicted["development_fixture_cases"]
    }

    checks: dict[str, dict[str, Any]] = {
        "the_repair_only_ever_withholds": {
            "class": PROSPECTIVE,
            "why": (
                "no unit may acquire a concrete record it did not carry under "
                "pin OFF. A repair that adds a statement is not withholding one"
            ),
            "predicted": predicted["predicts_no_unsettled_unit_is_definitely_classified"],
            "observed_violations": properties["no_unit_gained_a_definite_outcome"]["violations"],
            "pass": properties["no_unit_gained_a_definite_outcome"]["holds"],
        },
        "nothing_disappears_silently": {
            "class": PROSPECTIVE,
            "why": (
                "a unit that carried a record under pin OFF and carries none "
                "under pin ON has had a false statement replaced by no "
                "statement, which a fail-closed endpoint cannot score"
            ),
            "observed_violations": properties["no_unit_vanished_from_the_diff"]["violations"],
            "pass": properties["no_unit_vanished_from_the_diff"]["holds"],
        },
        "every_withheld_definite_record_is_restated": {
            "class": PROSPECTIVE,
            "why": (
                "the weaker half of the same rule: a unit may keep other records "
                "while losing its definite one, and it is still silenced about "
                "the thing that was withheld"
            ),
            "observed_violations": properties[
                "every_withheld_definite_record_is_restated_as_unresolved"
            ]["violations"],
            "pass": properties["every_withheld_definite_record_is_restated_as_unresolved"]["holds"],
        },
        "no_unsettled_identity_seeds_a_recompilation": {
            "class": PROSPECTIVE,
            "why": (
                "an unresolved unit that reaches `changed_logical_ids` is both "
                "unsettled and definitely classified; control 10's second half"
            ),
            "predicted": predicted["predicts_no_unresolved_unit_seeds_a_recompilation"],
            "observed_violations": properties[
                "no_unsettled_identity_is_also_definitely_classified"
            ]["violations"],
            "pass": properties["no_unsettled_identity_is_also_definitely_classified"]["holds"],
        },
        "the_definite_vocabulary_survives": {
            "class": PROSPECTIVE,
            "why": (
                "controls 3-6 say a settled decision is untouched. Over-quarantine "
                "is its own defect and would show here as a definite kind that "
                "pin OFF speaks and pin ON does not"
            ),
            "predicted": predicted["predicts_the_definite_vocabulary_survives"],
            "definite_kinds_under_pin_off": definite,
            "collapsed_under_pin_on": collapsed,
            "counts_pin_off": {kind: kinds_off.get(kind, 0) for kind in definite},
            "counts_pin_on": {kind: kinds_on.get(kind, 0) for kind in definite},
            "pass": bool(definite) and not collapsed,
        },
        "the_reference_arm_is_still_production": {
            "class": PROSPECTIVE,
            "why": (
                "pin OFF must still reproduce the INC-V2-047 defect. If it does "
                "not, the two arms are the same behaviour and every number in "
                "the differential is the repair compared with itself"
            ),
            "observed": properties["pin_off_still_reproduces_the_pre_repair_defect"]["observed"],
            "pass": properties["pin_off_still_reproduces_the_pre_repair_defect"]["holds"],
        },
        "the_quarantine_path_is_actually_exercised": {
            "class": PROSPECTIVE,
            "why": (
                "the quarantine must have MEMBERS on this corpus. Without them "
                "every check above is clean because it is watching nothing, "
                "which is this study's most-repeated defect"
            ),
            "membership_by_clause": membership,
            "records_emitted_by_reason": reasons_on,
            "declared_reasons": totals["declared_quarantine_reasons"],
            "why_membership_and_not_emission": (
                "clause (3) -- the member INC-V2-047 is about -- suppresses a "
                "false unit_removed while the record making it visible was "
                "already emitted by the AMBIGUOUS branch under the same id, so it "
                "contributes no `detail` of its own. Gating on emitted reasons "
                "would report the load-bearing clause as never firing"
            ),
            "pass": membership.get("total_members", 0) > 0,
        },
        "the_document_level_channel_is_untouched": {
            "class": PROSPECTIVE,
            "why": "the repair is about units; a structural record must not move",
            "observed_violations": properties["the_document_level_channel_is_untouched"][
                "violations"
            ],
            "pass": properties["the_document_level_channel_is_untouched"]["holds"],
        },
        "every_declared_control_has_a_test_and_a_red_test": {
            "class": STRUCTURAL,
            "why": (
                "a declared control with no test is a control that silently "
                "never ran; a control with no red test is a control that cannot "
                "fail. This is about the battery, not about the repair"
            ),
            "controls_total": predicted["controls_total"],
            "without_a_test": predicted["controls_without_a_test"],
            "without_a_red_test": predicted["controls_without_a_red_test"],
            "with_an_undeclared_red_mutation": predicted[
                "controls_with_an_undeclared_red_mutation"
            ],
            "pass": (
                predicted["controls_total"] == 10
                and not predicted["controls_without_a_test"]
                and not predicted["controls_without_a_red_test"]
                and not predicted["controls_with_an_undeclared_red_mutation"]
            ),
        },
        "the_nine_v1_development_fixtures_close": {
            "class": RETROSPECTIVE,
            "why": (
                "the repair was written after seeing these nine, so their closure "
                "is a development regression. REPORTED AND NEVER COUNTED. "
                "IDENTITY_CHANGE_MIGRATION_CLOSURE_V1 graded FAIL on INVARIANT_6 "
                "and that verdict is permanent, is not rescored here, and is not "
                "a denominator for anything"
            ),
            "fixture_cases": len(fixture_cases),
            "observed_withheld_removals": len(observed_cases),
            "fixtures_not_observed": sorted(fixture_cases - observed_cases),
            "observed_but_not_a_fixture": sorted(observed_cases - fixture_cases),
            "pass": observed_cases == fixture_cases,
        },
        "every_unresolved_record_is_on_the_unresolved_channel": {
            "class": TAUTOLOGICAL,
            "why": (
                "`_CHANGE_CHANNEL` maps IDENTITY_UNRESOLVED to UNRESOLVED, so an "
                "emitted record cannot be on another channel. Reported because it "
                "is the contract's own claim; labelled so nobody counts it as "
                "independent evidence. The half that is NOT tautological -- a unit "
                "carrying an unresolved record AND a definite one, which enters "
                "`changed_logical_ids` regardless -- is gated separately above"
            ),
            "observed_violations": properties[
                "no_unsettled_identity_is_also_definitely_classified"
            ]["violations"],
            "pass": properties["no_unsettled_identity_is_also_definitely_classified"]["holds"],
        },
    }

    by_class: dict[str, dict[str, int]] = {}
    for row in checks.values():
        bucket = by_class.setdefault(row["class"], {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += int(bool(row["pass"]))

    #: The verdict is over EVERY check, tautological and retrospective included:
    #: one of them failing is still a fact about the tree, and hiding it behind
    #: a class label would be the INC-V2-048 shape. What the labels change is
    #: what may be *counted as evidence* -- reported below, separately.
    verdict = "PASS" if all(row["pass"] for row in checks.values()) else "FAIL"

    return {
        "verdict": verdict,
        "checks": checks,
        "checks_by_class": by_class,
        "prospective_checks_passed": by_class.get(PROSPECTIVE, {}).get("passed", 0),
        "prospective_checks_total": by_class.get(PROSPECTIVE, {}).get("total", 0),
        "what_may_be_counted_as_evidence": (
            "the prospective checks only. The structural check is about the "
            "control battery, the retrospective check replays fixtures the "
            "repair was written after seeing, and the tautological check is true "
            "by construction"
        ),
        "reported_not_gated": {
            "why": (
                "no threshold in this repository is calibrated; a rate bar "
                "invented here would be an uncalibrated number presented as a "
                "measured one"
            ),
            "units_compared": totals["units_compared"],
            "units_identical_under_both_pins": totals["units_identical_under_both_pins"],
            "units_changed": totals["units_changed"],
            "identical_share_of_units_compared": totals["identical_share_of_units_compared"],
            "transitions": report["reported_not_gated"]["transitions"],
            "kind_counts_pin_off": kinds_off,
            "kind_counts_pin_on": kinds_on,
            "quarantine_reason_counts_pin_on": reasons_on,
            "quarantine_membership_by_clause": membership,
            "clauses_never_exercised_on_this_corpus": totals[
                "clauses_never_exercised_on_this_corpus"
            ],
            "clause_coverage_is_a_limit_not_a_failure": (
                "a contract clause the corpus never reaches is not a defect in "
                "the repair; it is a statement about what this run is evidence "
                "for. Reported so a later reader cannot mistake a PASS here for "
                "coverage of the whole contract"
            ),
            "unit_added_withheld": len(
                report["reported_not_gated"]["unit_added_withheld_and_stated_unresolved"]
            ),
            "unit_removed_withheld": len(
                report["reported_not_gated"]["unit_removed_withheld_and_stated_unresolved"]
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="pairs from the frozen universe")
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args()

    # Re-run rather than read the stored differential: a canary that gates on an
    # artifact it did not produce can pass against a stale one -- and the
    # Protected Core files under it are being edited by another lane, so "stale"
    # here is not a hypothetical.
    report = differential.run(args.limit)
    predicted = predictions_from_controls()
    result = gate(report, predicted)

    body = {
        "schema": SCHEMA,
        "rung": "4 -- canary",
        "limit": args.limit,
        "differential": {
            "schema": report["schema"],
            "verdict": report["verdict"],
            "population": report["population"],
            "subject_code": report["subject_code"],
        },
        "predictions_from_controls": predicted,
        **result,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / "canary.json"
    target.write_text(json.dumps(body, indent=1, ensure_ascii=False), encoding="utf-8")

    #: `artifacts/development/.../canary.json` is overwritten by the next run, so
    #: it cannot be what anything pins. A rung of this ladder has to be readable
    #: from something that cannot be rewritten underneath it.
    if args.write_receipt:
        body.update(write_immutable(STEM, body, tool=Path(__file__).resolve()))
        print("receipt:", body.get("receipt"))

    print(json.dumps(body, indent=1, ensure_ascii=False, default=str))
    print("written:", target)
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
