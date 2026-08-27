#!/usr/bin/env python3
"""Canary for the INC-V2-037 predicate switch: old and new, side by side, gated.

Rung 7 of `docs/COMPAT_IDENTITY_CHANGE_SEPARATION.md`. `identity_change_benchmark`
measures the disagreement between the two predicates over the whole cached
corpus. This tool asks the next question: **is the disagreement the shape the
adversarial controls said it would be?**

The predictions are not restated here. They are computed from
`tests/test_identity_change_migration.py::ADVERSARIAL` -- the same table the
controls run from -- so a control that is edited moves this gate with it. A
canary whose expectations are a hand-written copy of the controls' expectations
gates on nothing but the author's memory of them.

**What is gated, and what each check is worth:**

* `under_fire_is_empty` -- nothing the old predicate caught may be missed. The
  controls assert this on compatibility-decomposition probes, which is where
  the only possible counterexample could live. *Non-tautological*: a porting
  mistake in the CONTENT projection would show up here.
* `identity_continuity_undisturbed` -- every non-content change record is
  identical under both predicates, on every pair. This is the regression risk
  the whole ladder exists for, and it is the check most worth having.
  *Non-tautological.*
* `confirmed_defect_lineages_all_fire` -- the 14 E5-confirmed selective stale
  escapes must all appear in the disagreement set. A switch that costs
  over-fires and does not catch the cases it was built for is a bad trade
  reported as a good one. *Non-tautological.*
* `every_over_fire_confirmed_by_the_independent_facet_module` -- each
  disagreement, re-derived through `source_fact_ir/change_facets.py` rather
  than through `akc_cir`'s port of it, must show `CONTENT=changed`.
  *Non-tautological*: this is the drift check at corpus scale.
* `no_over_fire_is_canonical_form_only` -- **tautological, and recorded as
  such.** The new predicate folds NFC by construction, so it cannot fire on a
  canonical-form-only difference. It is reported because it is the over-fire
  bound the contract claims, and a reader is entitled to see it checked; it is
  labelled so nobody counts it as independent evidence.

**There is no rate threshold and there will not be one here.** The over-fire
rate is reported with its denominator and nothing is gated on it. No threshold
in this repository is calibrated, and inventing one so the canary goes green
would be presenting an uncalibrated number as a measured bar.

Usage::

    python tools/canary_identity_change.py           # whole corpus
    python tools/canary_identity_change.py --limit 40
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir", "tests"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))
ROOT = NS.parents[1]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

import change_facets as facets  # noqa: E402
import identity_change_benchmark as bench  # noqa: E402
from akc_cir.semantic_diff import CHANGE_FACET_SCHEMA  # noqa: E402
from evidence import write_immutable  # noqa: E402
from test_identity_change_migration import ADVERSARIAL  # noqa: E402

STEM = "identity-change-canary"
SCHEMA = "tavonel.v2.canary_identity_change.v1"
OUT_DIR = NS / "artifacts" / "development" / "identity_change_benchmark"


def predictions_from_controls() -> dict[str, Any]:
    """What the adversarial table says the corpus disagreement must look like.

    Read off the controls rather than written down again. Each row is
    `(name, before, after, expect_changed, why, outcome)`.
    """
    canonical_form_only = [
        row[0]
        for row in ADVERSARIAL
        if unicodedata.normalize("NFC", row[1]) == unicodedata.normalize("NFC", row[2])
    ]
    return {
        "controls_total": len(ADVERSARIAL),
        # No control fires the new predicate without the old one having been
        # wrong, so no control predicts an under-fire.
        "predicts_under_fire": False,
        # No control is permitted to become an add-plus-remove; the controls
        # assert that directly, so the corpus must show it too.
        "predicts_identity_disturbance": False,
        # Controls whose two texts are canonically equivalent must resolve
        # unchanged; if any such control expected `changed`, the bound below
        # would be a wrong prediction rather than a tautology.
        "canonical_form_only_controls": canonical_form_only,
        "canonical_form_only_controls_all_expect_unchanged": all(
            row[3] is False
            for row in ADVERSARIAL
            if unicodedata.normalize("NFC", row[1]) == unicodedata.normalize("NFC", row[2])
        ),
        "controls_expecting_changed": [row[0] for row in ADVERSARIAL if row[3]],
    }


def _over_fire_pairs(report: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in report["pairs"]:
        for over in row.get("over_fires", []):
            out.append({"lineage_id": row["lineage_id"], **over})
    return out


def gate(report: dict[str, Any], predicted: dict[str, Any]) -> dict[str, Any]:
    overall = report["overall"]
    over_fires = _over_fire_pairs(report)

    with_text = [o for o in over_fires if "before" in o and "after" in o]
    anomalies = [o for o in over_fires if "anomaly" in o]

    canonical_form_only = [
        o
        for o in with_text
        if unicodedata.normalize("NFC", o["before"]) == unicodedata.normalize("NFC", o["after"])
    ]
    facet_disagreements = [o for o in with_text if facets.CONTENT not in o["changed_facets"]]

    confirmed = set(report["confirmed_defect_reference"].get("lineages") or [])
    fired = set(overall.get("confirmed_defect_lineages_with_an_over_fire") or [])
    missing_confirmed = sorted(confirmed - fired)

    checks = {
        "under_fire_is_empty": {
            "tautological": False,
            "predicted": predicted["predicts_under_fire"],
            "observed_count": overall["under_fire_units"],
            "pass": overall["under_fire_units"] == 0,
        },
        "identity_continuity_undisturbed": {
            "tautological": False,
            "predicted": predicted["predicts_identity_disturbance"],
            "observed_count": overall["identity_records_disagree_pairs"],
            "pass": overall["identity_records_disagree_pairs"] == 0,
        },
        "confirmed_defect_lineages_all_fire": {
            "tautological": False,
            "expected_lineages": len(confirmed),
            "fired_lineages": len(fired & confirmed),
            "missing": missing_confirmed,
            "pass": bool(confirmed) and not missing_confirmed,
        },
        "every_over_fire_confirmed_by_the_independent_facet_module": {
            "tautological": False,
            "checked": len(with_text),
            "disagreements": [o["logical_id"] for o in facet_disagreements],
            "pass": not facet_disagreements,
        },
        "no_over_fire_is_canonical_form_only": {
            "tautological": True,
            "why": (
                "the CONTENT projection normalizes NFC, so a canonical-form-only "
                "difference cannot reach `changed`; reported, not counted as evidence"
            ),
            "controls_backing_it": predicted["canonical_form_only_controls"],
            "controls_agree": predicted["canonical_form_only_controls_all_expect_unchanged"],
            "observed_count": len(canonical_form_only),
            "pass": not canonical_form_only,
        },
        "no_over_fire_lacks_a_facet_account": {
            "tautological": False,
            "why": (
                "an over-fire with no matched pair reproduced means the benchmark's "
                "reproduction of `diff_documents`' matching has drifted"
            ),
            "observed_count": len(anomalies),
            "pass": not anomalies,
        },
    }

    non_tautological = {k: v for k, v in checks.items() if not v["tautological"]}
    verdict = "PASS" if all(v["pass"] for v in checks.values()) else "FAIL"
    return {
        "verdict": verdict,
        "checks": checks,
        "non_tautological_checks_passed": sum(1 for v in non_tautological.values() if v["pass"]),
        "non_tautological_checks_total": len(non_tautological),
        "reported_not_gated": {
            "why": (
                "no threshold in this repository is calibrated; a rate bar invented "
                "here would be an uncalibrated number presented as a measured one"
            ),
            "over_fire_units": overall["over_fire_units"],
            "over_fire_denominator": overall["over_fire_denominator"],
            "over_fire_rate_over_matched_pairs": overall["over_fire_rate_over_matched_pairs"],
            "over_fires_on_confirmed_defect_lineages": overall[
                "over_fires_on_confirmed_defect_lineages"
            ],
            "over_fires_not_on_a_confirmed_defect_lineage": (
                overall["over_fire_units"] - overall["over_fires_on_confirmed_defect_lineages"]
            ),
            "over_fire_difference_classes": overall["over_fire_difference_classes"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="pairs per cohort")
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args()

    # Re-run rather than read the stored benchmark: a canary that gates on an
    # artifact it did not produce can pass against a stale one.
    report = bench.run(args.limit)
    predicted = predictions_from_controls()
    result = gate(report, predicted)

    body = {
        "schema": SCHEMA,
        "facet_contract": facets.SCHEMA,
        "facet_contract_declared_by_semantic_diff": CHANGE_FACET_SCHEMA,
        "contracts_agree": facets.SCHEMA == CHANGE_FACET_SCHEMA,
        "limit": args.limit,
        "corpus": {
            "pairs_considered": report["overall"]["pairs_considered"],
            "pairs_resolved": report["overall"]["pairs_resolved"],
            "pairs_unresolved": report["overall"]["pairs_unresolved"],
            "matched_pairs_total": report["overall"]["matched_pairs_total"],
        },
        "predictions_from_adversarial_controls": predicted,
        **result,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / "canary.json"
    target.write_text(json.dumps(body, indent=1, ensure_ascii=False), encoding="utf-8")

    #: `artifacts/development/.../canary.json` is overwritten by the next run, so
    #: it cannot be what anything pins. The freeze gate has to read a rung of this
    #: ladder from something that cannot be rewritten underneath it -- the same
    #: reason the claim matrix stopped pointing at `receipts/latest/`.
    if args.write_receipt:
        body.update(write_immutable(STEM, body, tool=Path(__file__).resolve()))
        print("receipt:", body.get("receipt"))

    print(json.dumps(body, indent=1, ensure_ascii=False, default=str))
    print("written:", target)
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
