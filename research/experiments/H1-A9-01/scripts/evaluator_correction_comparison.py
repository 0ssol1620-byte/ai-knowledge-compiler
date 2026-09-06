#!/usr/bin/env python3
"""The same frozen evidence, measured twice: before and after the instrument fix.

This is not a re-run of the experiment. The model outputs, the gate, the
operating point, the severe-error definition and the holdout membership are all
unchanged and were never touched. What changed is the measuring device: the
evaluator used to pick its matching algorithm from a wall-clock timeout, and now
always runs the exact matcher.

Reporting both columns side by side is the whole point. A corrected instrument
that quietly replaced the published numbers would be indistinguishable from
tuning until the answer looked right, so the pre-correction result stays on the
record next to the corrected one, whichever way it moves.

If the primary result survives, the confirmatory claim is sealed on the
corrected column. If it does not, that is the finding, and the instrument does
not get adjusted again to recover it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FALLBACK_LINE = re.compile(
    r"\[(?:timeout-fallback|match-timeout|quick-match-timeout)\] (.+?): "
)


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.resolve().read_text(encoding="utf-8"))


def fallback_pages(logs: list[Path]) -> set[str]:
    pages: set[str] = set()
    for log in logs:
        if log.is_file():
            pages |= set(
                FALLBACK_LINE.findall(log.read_text(encoding="utf-8", errors="replace"))
            )
    return pages


def column(result: dict[str, Any]) -> dict[str, Any]:
    primary, secondary = result["primary"], result["secondary"]
    return {
        "pages_tested": result["pages_tested"],
        "accepted_pages": primary["accepted_pages"],
        "accepted_severe": primary["accepted_severe"],
        "abstained_pages": primary["abstained_pages"],
        "abstained_severe": primary["abstained_severe"],
        "accepted_severe_rate": secondary["selective_severe_error_rate"],
        "abstained_severe_rate": secondary["abstained_severe_error_rate"],
        "baseline_severe_rate": secondary["baseline_severe_error_rate"],
        "risk_difference": (
            secondary["abstained_severe_error_rate"]
            - secondary["selective_severe_error_rate"]
        ),
        "risk_difference_95_ci_bootstrap": secondary["rate_difference_95_ci_bootstrap"],
        "accepted_rate_95_ci_wilson": secondary["accepted_rate_95_ci_wilson"],
        "abstained_rate_95_ci_wilson": secondary["abstained_rate_95_ci_wilson"],
        "absolute_risk_reduction": secondary["absolute_risk_reduction"],
        "relative_risk_reduction": secondary["relative_risk_reduction"],
        "coverage": secondary["coverage"],
        "fisher_exact_p": primary["p_value"],
        "rejects_at_alpha": primary["rejects_at_alpha"],
        "total_severe": primary["accepted_severe"] + primary["abstained_severe"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--before-logs", type=Path, nargs="*", default=[])
    parser.add_argument("--after-logs", type=Path, nargs="*", default=[])
    parser.add_argument("--determinism-receipt", type=Path)
    parser.add_argument("--independence-receipt", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    before, after = load(args.before), load(args.after)
    before_column, after_column = column(before), column(after)

    # Per-page label movement caused purely by the instrument change.
    before_pages = {p["image_path"]: p for p in before["pages"]}
    after_pages = {p["image_path"]: p for p in after["pages"]}
    shared = sorted(set(before_pages) & set(after_pages))

    flips = []
    for page in shared:
        was, now = before_pages[page], after_pages[page]
        if was["severe"] != now["severe"]:
            flips.append(
                {
                    "page": page,
                    "was_severe": was["severe"],
                    "now_severe": now["severe"],
                    "before_edit": was["official_text_edit"],
                    "after_edit": now["official_text_edit"],
                    "accepted": now["accepted"],
                }
            )

    gate_changed = [
        page for page in shared
        if before_pages[page]["accepted"] != after_pages[page]["accepted"]
    ]

    before_fb = fallback_pages([p.resolve() for p in args.before_logs])
    after_fb = fallback_pages([p.resolve() for p in args.after_logs])

    def rates(flagged: set[str], source: dict[str, dict[str, Any]]) -> dict[str, Any]:
        acc = [p for p in source.values() if p["accepted"]]
        abst = [p for p in source.values() if not p["accepted"]]
        return {
            "fallback_pages": len(flagged),
            "accepted_fallback_rate": (
                sum(1 for p in acc if p["image_path"] in flagged) / len(acc)
                if acc else None
            ),
            "abstained_fallback_rate": (
                sum(1 for p in abst if p["image_path"] in flagged) / len(abst)
                if abst else None
            ),
        }

    survived = after_column["rejects_at_alpha"]
    direction_held = (
        after_column["abstained_severe_rate"] > after_column["accepted_severe_rate"]
    )

    # "Survived" is a statement about the decision rule and nothing more. Two
    # results can both reject and still differ in how much they support, so the
    # magnitude is reported next to the verdict rather than left to be inferred
    # from a p-value that moved by an order of magnitude.
    def ci_excludes_zero(col: dict[str, Any]) -> bool:
        low, high = col["risk_difference_95_ci_bootstrap"]
        return low > 0.0 or high < 0.0

    before_excludes = ci_excludes_zero(before_column)
    after_excludes = ci_excludes_zero(after_column)
    artefact_share = (
        1.0 - after_column["risk_difference"] / before_column["risk_difference"]
        if before_column["risk_difference"]
        else None
    )

    receipt = {
        "schema": "tavonel.a9-evaluator-correction-comparison.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "what_changed": "the evaluator only",
        "what_did_not_change": [
            "model outputs (both frozen 800-page runs, byte-identical files)",
            "the gate and its operating point",
            "the severe-error definition (text-block edit distance > 0.10)",
            "holdout membership",
            "the statistical test and alpha",
        ],
        "before": before_column,
        "after": after_column,
        "deltas": {
            "accepted_severe_rate": after_column["accepted_severe_rate"]
            - before_column["accepted_severe_rate"],
            "abstained_severe_rate": after_column["abstained_severe_rate"]
            - before_column["abstained_severe_rate"],
            "risk_difference": after_column["risk_difference"]
            - before_column["risk_difference"],
            "fisher_exact_p": after_column["fisher_exact_p"]
            - before_column["fisher_exact_p"],
            "total_severe": after_column["total_severe"] - before_column["total_severe"],
        },
        "severe_label_flips_caused_by_the_correction": {
            "count": len(flips),
            "became_severe": sum(1 for f in flips if f["now_severe"]),
            "stopped_being_severe": sum(1 for f in flips if not f["now_severe"]),
            "among_accepted_pages": sum(1 for f in flips if f["accepted"]),
            "among_abstained_pages": sum(1 for f in flips if not f["accepted"]),
            "pages": flips,
        },
        "gate_decisions_that_changed": gate_changed,
        "fallback_rates_by_gate_decision": {
            "before": rates(before_fb, before_pages),
            "after": rates(after_fb, after_pages),
        },
        "determinism_receipt": (
            str(args.determinism_receipt) if args.determinism_receipt else None
        ),
        "independence_receipt": (
            str(args.independence_receipt) if args.independence_receipt else None
        ),
        "primary_result_survives_the_correction": survived,
        "direction_unchanged": direction_held,
        "effect_magnitude": {
            "risk_difference_ci_excludes_zero_before": before_excludes,
            "risk_difference_ci_excludes_zero_after": after_excludes,
            "share_of_the_measured_effect_that_was_a_measurement_artefact": (
                artefact_share
            ),
            "reading": (
                "the pre-registered decision rule is the Fisher exact test, and "
                "it still rejects. The bootstrap interval on the risk difference "
                "is a different and more conservative procedure over a 101-page "
                "abstained arm, and after the correction it includes zero. The "
                "association survives; a claim about its magnitude does not."
                if survived and not after_excludes
                else "decision rule and interval agree"
            ),
        },
        "verdict": (
            "the confirmatory result holds under a deterministic instrument"
            if survived
            else "the confirmatory result does NOT hold under a deterministic "
            "instrument; this is recorded as the finding and the instrument is "
            "not adjusted again to recover it"
        ),
        "why_this_is_not_holdout_reuse": (
            "the holdout was not re-selected, the gate was not re-tuned and the "
            "endpoint was not redefined. A defect was found in the measuring "
            "device -- one that was demonstrably correlated with the comparison "
            "being measured, not merely noisy -- and the same frozen evidence was "
            "measured again with the device repaired. Both readings are kept."
        ),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)

    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    rows = (
        ("pages tested", "pages_tested", "{:d}"),
        ("accepted / severe", None, None),
        ("abstained / severe", None, None),
        ("accepted severe rate", "accepted_severe_rate", "{:.4f}"),
        ("abstained severe rate", "abstained_severe_rate", "{:.4f}"),
        ("risk difference", "risk_difference", "{:.4f}"),
        ("Fisher exact p", "fisher_exact_p", "{:.6f}"),
        ("total severe", "total_severe", "{:d}"),
        ("coverage", "coverage", "{:.4f}"),
    )
    print(f"{'quantity':26} {'before':>14} {'after':>14}")
    for label, key, fmt in rows:
        if key is None:
            if label.startswith("accepted /"):
                b = f"{before_column['accepted_pages']} / {before_column['accepted_severe']}"
                a = f"{after_column['accepted_pages']} / {after_column['accepted_severe']}"
            else:
                b = f"{before_column['abstained_pages']} / {before_column['abstained_severe']}"
                a = f"{after_column['abstained_pages']} / {after_column['abstained_severe']}"
        else:
            b, a = fmt.format(before_column[key]), fmt.format(after_column[key])
        print(f"{label:26} {b:>14} {a:>14}")
    print(f"\nCI before: {before_column['risk_difference_95_ci_bootstrap']}")
    print(f"CI after : {after_column['risk_difference_95_ci_bootstrap']}")
    print(f"severe label flips caused by the correction: {len(flips)}")
    print(f"gate decisions changed: {len(gate_changed)} (must be 0)")
    print(f"\nCI excludes zero -- before: {before_excludes}  after: {after_excludes}")
    if artefact_share is not None:
        print(
            "share of the effect that was a measurement artefact: "
            f"{artefact_share:.1%}"
        )
    print(f"\n{receipt['verdict']}")
    print(f"receipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
