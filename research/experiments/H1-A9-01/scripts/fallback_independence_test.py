#!/usr/bin/env python3
"""Is the old evaluator's timeout fallback independent of the gate's decision?

This is the question that turns a measurement quirk into a defect in the
endpoint, and it was assumed rather than tested in the first write-up of the
confirmatory result. The assumed reasoning was:

    the gate never reads the evaluator, so evaluator noise is independent of the
    accepted/abstained split; independent misclassification of a binary outcome
    attenuates an association toward the null rather than manufacturing one;
    therefore the p-value is conservative.

The first clause does not follow from the second. The gate not *reading* the
evaluator does not make the evaluator's failure mode independent of the gate's
decision. Both are functions of the same page. The old evaluator fell back to an
approximate matcher when matching took too long, and matching takes long on
pages with many elements and disordered content -- which are plausibly the same
pages a disagreement-based gate abstains on.

So it is tested directly, as a 2x2 of gate decision against whether the page
ever hit the timeout fallback, with Fisher's exact test.

If they are independent, the original reassurance stands and the correction is
hygiene. If they are not, the noise is correlated with the comparison, the
attenuation argument fails in both directions, and the confirmatory evidence has
to be re-measured with a corrected instrument before it can be relied on.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from holdout_power_calculation import fisher_exact_two_sided

FALLBACK_LINE = re.compile(
    r"\[(?:timeout-fallback|match-timeout|quick-match-timeout)\] (.+?): "
)


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def fallback_pages(log: Path) -> set[str]:
    if not log.is_file():
        return set()
    return set(FALLBACK_LINE.findall(log.read_text(encoding="utf-8", errors="replace")))


def contingency(
    pages: list[dict[str, Any]], flagged: set[str]
) -> dict[str, Any]:
    accepted_fallback = sum(1 for p in pages if p["accepted"] and p["image_path"] in flagged)
    accepted_clean = sum(1 for p in pages if p["accepted"] and p["image_path"] not in flagged)
    abstained_fallback = sum(
        1 for p in pages if not p["accepted"] and p["image_path"] in flagged
    )
    abstained_clean = sum(
        1 for p in pages if not p["accepted"] and p["image_path"] not in flagged
    )
    accepted_total = accepted_fallback + accepted_clean
    abstained_total = abstained_fallback + abstained_clean
    p_value = fisher_exact_two_sided(
        accepted_fallback, accepted_clean, abstained_fallback, abstained_clean
    )
    accepted_rate = accepted_fallback / accepted_total if accepted_total else 0.0
    abstained_rate = abstained_fallback / abstained_total if abstained_total else 0.0
    return {
        "accepted_with_fallback": accepted_fallback,
        "accepted_without_fallback": accepted_clean,
        "abstained_with_fallback": abstained_fallback,
        "abstained_without_fallback": abstained_clean,
        "accepted_fallback_rate": accepted_rate,
        "abstained_fallback_rate": abstained_rate,
        "rate_ratio_abstained_over_accepted": (
            abstained_rate / accepted_rate if accepted_rate else None
        ),
        "fisher_exact_p": p_value,
        "independent_at_0_05": p_value >= 0.05,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmatory-result", type=Path, required=True)
    parser.add_argument(
        "--stdout-log", type=Path, nargs="+", required=True,
        help="evaluator stdout logs; the union of their fallbacks is the primary test",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = json.loads(args.confirmatory_result.resolve().read_text(encoding="utf-8"))
    pages = result["pages"]

    per_log = {}
    union: set[str] = set()
    for log in args.stdout_log:
        flagged = fallback_pages(log.resolve())
        per_log[log.name if log.name != "stdout.log" else str(log.parent.name)] = {
            "log": str(log.resolve()),
            "fallback_pages": len(flagged),
            **contingency(pages, flagged),
        }
        union |= flagged

    primary = contingency(pages, union)
    independent = primary["independent_at_0_05"]

    # Does the fallback also track the outcome? If it tracks both the gate and
    # the outcome it is a confounder, not merely correlated noise.
    severe_fallback = sum(1 for p in pages if p["severe"] and p["image_path"] in union)
    severe_clean = sum(1 for p in pages if p["severe"] and p["image_path"] not in union)
    ok_fallback = sum(1 for p in pages if not p["severe"] and p["image_path"] in union)
    ok_clean = sum(1 for p in pages if not p["severe"] and p["image_path"] not in union)
    outcome_p = fisher_exact_two_sided(
        severe_fallback, severe_clean, ok_fallback, ok_clean
    )

    receipt = {
        "schema": "tavonel.a9-fallback-independence-test.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "DIAGNOSTIC on the pre-correction evaluator",
        "pages_tested": len(pages),
        "fallback_pages_in_union": len(union),
        "primary_gate_vs_fallback": primary,
        "per_evaluation_run": per_log,
        "fallback_vs_outcome": {
            "severe_with_fallback": severe_fallback,
            "severe_without_fallback": severe_clean,
            "not_severe_with_fallback": ok_fallback,
            "not_severe_without_fallback": ok_clean,
            "severe_rate_among_fallback_pages": (
                severe_fallback / (severe_fallback + ok_fallback)
                if (severe_fallback + ok_fallback)
                else None
            ),
            "severe_rate_among_other_pages": (
                severe_clean / (severe_clean + ok_clean)
                if (severe_clean + ok_clean)
                else None
            ),
            "fisher_exact_p": outcome_p,
        },
        "verdict": (
            "INDEPENDENT -- the attenuation argument holds and the correction is "
            "hygiene"
            if independent
            else "NOT INDEPENDENT -- the measurement's failure mode is correlated "
            "with the comparison being measured, so the 'independent noise only "
            "attenuates' argument does not apply and the evidence must be "
            "re-measured with a deterministic instrument"
        ),
        "why_this_had_to_be_tested_rather_than_argued": (
            "the gate not reading the evaluator makes the gate independent of the "
            "evaluator's *output*, not of the evaluator's *failure mode*. Both the "
            "gate decision and the matcher's running time are functions of the "
            "same page, and long pages with disordered content are plausibly both "
            "slow to match and likely to be abstained on. Independence between "
            "two quantities computed from the same object is a claim about the "
            "world, and claims about the world get tested."
        ),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)

    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("=== fallback occurrence vs gate decision ===")
    print(f"accepted : {primary['accepted_with_fallback']:3} / "
          f"{primary['accepted_with_fallback'] + primary['accepted_without_fallback']:3}"
          f"  rate {primary['accepted_fallback_rate']:.4f}")
    print(f"abstained: {primary['abstained_with_fallback']:3} / "
          f"{primary['abstained_with_fallback'] + primary['abstained_without_fallback']:3}"
          f"  rate {primary['abstained_fallback_rate']:.4f}")
    print(f"Fisher exact two-sided p = {primary['fisher_exact_p']:.6f}")
    print(f"independent at 0.05: {independent}")
    print(f"\nfallback vs outcome: p = {outcome_p:.6f}")
    print(f"\n{receipt['verdict']}")
    print(f"receipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
