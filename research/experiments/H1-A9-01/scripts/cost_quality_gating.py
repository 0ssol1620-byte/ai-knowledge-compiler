#!/usr/bin/env python3
"""R4: what does each acceptance gate cost, and what does it buy?

Four configurations on the same 198 pages, priced from measured GPU time rather
than from a list price:

  1. single run                -- what the product does today
  2. stability gate            -- the same parser run twice, abstain where the
                                  two runs disagree
  3. agreement gate            -- a second parser, abstain where the two parsers
                                  disagree
  4. stability + agreement     -- abstain if either fires

Two rules make the comparison mean something:

  * **Cost is GPU-seconds per page first, dollars second.** The two parsers were
    measured on different clouds at different hourly rates ($0.34/hr COMMUNITY
    for this run, $0.74/hr for the frozen MinerU campaign), so dollars alone
    would compare hosting decisions rather than work done. Both are reported and
    each rate is named.

  * **Gates are compared at matched coverage.** A gate that abstains more will
    look better on selective error for that reason alone. The stability gate's
    abstention rate is what it is -- the pages either differed between runs or
    they did not -- so the agreement gate is evaluated at the same coverage
    rather than at its own most flattering one.

It also measures whether the two signals are redundant. If they abstain on the
same pages, the second parser buys nothing over running the first one twice; if
they catch different errors, it does, and the extra cost is justified or not on
those grounds rather than on a preference.

Everything here is exploratory. The operating points were chosen after seeing
this corpus, and the confirmatory protocol is a separate frozen document.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.critical_tokens import verify_critical_tokens  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repaired_output_instruments import evidence_validity  # noqa: E402

SEVERE = 0.10
MODERATE = 0.05


def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    rows, cols, total = (a + b, c + d), (a + c, b + d), a + b + c + d
    if total == 0 or 0 in rows or 0 in cols:
        return 1.0

    def probability(x: int) -> float:
        return (
            math.comb(cols[0], x)
            * math.comb(cols[1], rows[0] - x)
            / math.comb(total, rows[0])
        )

    observed = probability(a)
    low, high = max(0, rows[0] - cols[1]), min(rows[0], cols[0])
    return min(
        1.0,
        sum(
            probability(x)
            for x in range(low, high + 1)
            if probability(x) <= observed + 1e-12
        ),
    )


def aurc(pages: list[dict[str, Any]], signal: str, key: str) -> float:
    """Area under the risk-coverage curve, lower is better.

    Averaged over every coverage the corpus admits rather than over a chosen
    grid, so it does not inherit a threshold choice.
    """
    ordered = sorted(pages, key=lambda p: p[signal], reverse=True)
    risks = []
    bad = 0
    for index, page in enumerate(ordered, start=1):
        bad += 1 if page[key] else 0
        risks.append(bad / index)
    return statistics.mean(risks)


def gate_report(
    pages: list[dict[str, Any]],
    accepted: list[dict[str, Any]],
    key: str,
    baseline_errors: int,
) -> dict[str, Any]:
    abstained = [p for p in pages if p not in accepted]
    accepted_bad = sum(1 for p in accepted if p[key])
    abstained_bad = sum(1 for p in abstained if p[key])
    return {
        "coverage": len(accepted) / len(pages),
        "abstention_rate": len(abstained) / len(pages),
        "accepted_pages": len(accepted),
        "selective_error_rate": accepted_bad / len(accepted) if accepted else 0.0,
        "errors_accepted": accepted_bad,
        "errors_abstained": abstained_bad,
        "severe_errors_avoided": baseline_errors - accepted_bad,
        "fisher_exact_p_accepted_vs_abstained": fisher_exact_two_sided(
            accepted_bad,
            len(accepted) - accepted_bad,
            abstained_bad,
            len(abstained) - abstained_bad,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-a-predictions", type=Path, required=True)
    parser.add_argument("--run-a-artifacts", type=Path, required=True)
    parser.add_argument("--run-b-predictions", type=Path, required=True)
    parser.add_argument("--second-parser-predictions", type=Path, required=True)
    parser.add_argument("--run-a-receipt", type=Path, required=True)
    parser.add_argument("--run-b-receipt", type=Path, required=True)
    parser.add_argument("--second-parser-cost", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    edit_a = json.loads(
        (args.run_a_artifacts.resolve() / "text_block_per_page_edit.json").read_text(
            encoding="utf-8"
        )
    )
    samples = json.loads(args.ground_truth.resolve().read_text(encoding="utf-8"))
    receipt_a = json.loads(args.run_a_receipt.resolve().read_text(encoding="utf-8"))
    receipt_b = json.loads(args.run_b_receipt.resolve().read_text(encoding="utf-8"))
    mineru_cost = json.loads(args.second_parser_cost.resolve().read_text(encoding="utf-8"))

    pages: list[dict[str, Any]] = []
    for sample in samples:
        image = str(sample["page_info"]["image_path"])
        if image not in edit_a:
            continue
        stem = Path(image).stem
        first = (args.run_a_predictions.resolve() / f"{stem}.md").read_text("utf-8")
        second = (args.run_b_predictions.resolve() / f"{stem}.md").read_text("utf-8")
        other = (args.second_parser_predictions.resolve() / f"{stem}.md").read_text("utf-8")
        pages.append(
            {
                "image_path": image,
                "stable": first == second,
                "agreement": 1.0
                / (1.0 + len(verify_critical_tokens(first, other).mismatches)),
                "evidence_validity": evidence_validity(first),
                "severe": float(edit_a[image]) > SEVERE,
                "moderate": float(edit_a[image]) > MODERATE,
            }
        )

    total = len(pages)
    baseline_severe = sum(1 for p in pages if p["severe"])

    # --- cost, measured -----------------------------------------------------
    ovis_inference = float(receipt_a["inference_seconds"])
    ovis_inference_b = float(receipt_b["inference_seconds"])
    ovis_seconds_per_page = statistics.mean(
        [ovis_inference / 200.0, ovis_inference_b / 200.0]
    )
    ovis_rate = 0.34  # COMMUNITY RTX 4090, the rate this run was billed at
    healthy = mineru_cost["healthy_worker_only"]
    mineru_seconds_per_page = 3600.0 / float(healthy["pages_per_pod_hour"])
    mineru_rate = float(mineru_cost["hourly_rate_usd"])

    def money(seconds_per_page: float, rate: float) -> float:
        return seconds_per_page / 3600.0 * rate * 1000.0

    configurations: dict[str, dict[str, Any]] = {}

    configurations["single_run"] = {
        "description": "one pass of the gated parser; accept everything",
        "gpu_seconds_per_page": ovis_seconds_per_page,
        "usd_per_1000_pages": money(ovis_seconds_per_page, ovis_rate),
        "pages_per_pod_hour": 3600.0 / ovis_seconds_per_page,
        **gate_report(pages, pages, "severe", baseline_severe),
    }

    # An output-only gate: no second run, no second parser, no extra GPU second.
    # Its operating point is "the output states nothing internally malformed",
    # which is a defect count of zero rather than a tuned threshold.
    clean_evidence = [p for p in pages if p["evidence_validity"] >= 1.0]
    configurations["evidence_validity_gate"] = {
        "description": "one pass; abstain where the output's own dates, numbers, "
        "currency or signs are malformed. Costs no additional inference.",
        "gpu_seconds_per_page": ovis_seconds_per_page,
        "usd_per_1000_pages": money(ovis_seconds_per_page, ovis_rate),
        "pages_per_pod_hour": 3600.0 / ovis_seconds_per_page,
        **gate_report(pages, clean_evidence, "severe", baseline_severe),
    }

    stable_accept = [p for p in pages if p["stable"]]
    configurations["stability_gate"] = {
        "description": "two passes of the gated parser; abstain where they differ",
        "gpu_seconds_per_page": 2 * ovis_seconds_per_page,
        "usd_per_1000_pages": money(2 * ovis_seconds_per_page, ovis_rate),
        "pages_per_pod_hour": 3600.0 / (2 * ovis_seconds_per_page),
        **gate_report(pages, stable_accept, "severe", baseline_severe),
    }

    # Matched coverage: the agreement gate abstains on exactly as many pages as
    # the stability gate did, taking the least-agreeing ones first.
    matched = len(stable_accept)
    by_agreement = sorted(pages, key=lambda p: p["agreement"], reverse=True)
    agreement_accept = by_agreement[:matched]
    configurations["agreement_gate_matched_coverage"] = {
        "description": "one pass each of two parsers; abstain on the least-agreeing "
        "pages, at the same coverage the stability gate reached",
        "gpu_seconds_per_page": ovis_seconds_per_page + mineru_seconds_per_page,
        "usd_per_1000_pages": money(ovis_seconds_per_page, ovis_rate)
        + money(mineru_seconds_per_page, mineru_rate),
        "pages_per_pod_hour": 3600.0
        / (ovis_seconds_per_page + mineru_seconds_per_page),
        **gate_report(pages, agreement_accept, "severe", baseline_severe),
    }

    agreement_floor = agreement_accept[-1]["agreement"] if agreement_accept else 0.0
    both_accept = [
        p for p in pages if p["stable"] and p["agreement"] >= agreement_floor
    ]
    all_three = [
        p
        for p in pages
        if p["stable"]
        and p["agreement"] >= agreement_floor
        and p["evidence_validity"] >= 1.0
    ]
    configurations["all_three_signals"] = {
        "description": "three passes; abstain if any of the three signals fires",
        "gpu_seconds_per_page": 2 * ovis_seconds_per_page + mineru_seconds_per_page,
        "usd_per_1000_pages": money(2 * ovis_seconds_per_page, ovis_rate)
        + money(mineru_seconds_per_page, mineru_rate),
        "pages_per_pod_hour": 3600.0
        / (2 * ovis_seconds_per_page + mineru_seconds_per_page),
        **gate_report(pages, all_three, "severe", baseline_severe),
    }

    configurations["stability_and_agreement"] = {
        "description": "three passes total; abstain if either signal fires",
        "gpu_seconds_per_page": 2 * ovis_seconds_per_page + mineru_seconds_per_page,
        "usd_per_1000_pages": money(2 * ovis_seconds_per_page, ovis_rate)
        + money(mineru_seconds_per_page, mineru_rate),
        "pages_per_pod_hour": 3600.0
        / (2 * ovis_seconds_per_page + mineru_seconds_per_page),
        **gate_report(pages, both_accept, "severe", baseline_severe),
    }

    # --- are the two signals redundant? -------------------------------------
    malformed = {p["image_path"] for p in pages if p["evidence_validity"] < 1.0}
    unstable = {p["image_path"] for p in pages if not p["stable"]}
    low_agreement = {p["image_path"] for p in by_agreement[matched:]}
    severe_pages = {p["image_path"] for p in pages if p["severe"]}
    complementarity = {
        "unstable_pages": len(unstable),
        "low_agreement_pages": len(low_agreement),
        "flagged_by_both": len(unstable & low_agreement),
        "flagged_by_stability_only": len(unstable - low_agreement),
        "flagged_by_agreement_only": len(low_agreement - unstable),
        "jaccard": (
            len(unstable & low_agreement) / len(unstable | low_agreement)
            if unstable | low_agreement
            else 0.0
        ),
        "severe_errors_caught_by_stability_only": len(
            (unstable - low_agreement) & severe_pages
        ),
        "severe_errors_caught_by_agreement_only": len(
            (low_agreement - unstable) & severe_pages
        ),
        "severe_errors_caught_by_both": len(unstable & low_agreement & severe_pages),
        "severe_errors_caught_by_neither": len(
            severe_pages - (unstable | low_agreement)
        ),
        "evidence_validity_flags": len(malformed),
        "severe_errors_caught_by_evidence_only": len(
            (malformed - unstable - low_agreement) & severe_pages
        ),
        "severe_errors_caught_by_any_of_three": len(
            (malformed | unstable | low_agreement) & severe_pages
        ),
        "severe_errors_caught_by_none_of_three": len(
            severe_pages - (malformed | unstable | low_agreement)
        ),
        "pages_flagged_by_any_of_three": len(malformed | unstable | low_agreement),
        "reading": (
            "If the two sets barely overlap and each catches severe errors the "
            "other misses, the second parser is buying coverage the second run "
            "cannot, and 'a second parser is unnecessary' is not established."
        ),
    }

    receipt = {
        "schema": "tavonel.r4-cost-quality-gating.v1",
        "status": "EXPLORATORY -- operating points chosen after seeing this corpus",
        "page_count": total,
        "severe_error_definition": f"official text edit distance > {SEVERE}",
        "baseline_severe_errors": baseline_severe,
        "cost_basis": {
            "gated_parser": {
                "candidate_id": "ovisocr2-0.9b-vllm-0.22.1",
                "measured_inference_seconds_run_1": ovis_inference,
                "measured_inference_seconds_run_2": ovis_inference_b,
                "model_load_seconds_run_1": 150.086,
                "hourly_rate_usd": ovis_rate,
                "cloud": "COMMUNITY",
                "note": "model load is excluded from per-page cost; it is paid once "
                "per pod and amortises to near zero at corpus scale, and including "
                "it would price a 200-page run as if it were the steady state",
            },
            "second_parser": {
                "candidate_id": "mineru-3.4.4-vlm",
                "pages_per_pod_hour": healthy["pages_per_pod_hour"],
                "usd_per_1000_pages_as_published": healthy["usd_per_1000_pages"],
                "hourly_rate_usd": mineru_rate,
                "cloud": "not COMMUNITY; the frozen campaign rate",
                "note": "the healthy-worker rate, not the whole-campaign rate of "
                f"{mineru_cost['whole_campaign']['usd_per_1000_pages']} USD/1000, "
                "which includes every stall and retry the campaign hit",
            },
            "rates_differ": (
                "The two parsers were billed at different hourly rates on different "
                "clouds. GPU-seconds per page is the hardware-neutral comparison; "
                "the dollar column mixes in a hosting decision and is reported with "
                "each rate named rather than blended."
            ),
        },
        "configurations": configurations,
        "risk_coverage": {
            "aurc_stability": aurc(
                [{**p, "s": 1.0 if p["stable"] else 0.0} for p in pages], "s", "severe"
            ),
            "aurc_agreement": aurc(pages, "agreement", "severe"),
            "note": "area under the risk-coverage curve, lower is better",
        },
        "signal_complementarity": complementarity,
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(
        f"{'configuration':34} {'gpu s/pg':>9} {'$/1k':>7} {'cov':>6} "
        f"{'abst':>6} {'sev err':>8} {'avoided':>8} {'p':>8}"
    )
    for name, data in configurations.items():
        print(
            f"{name:34} {data['gpu_seconds_per_page']:9.2f} "
            f"{data['usd_per_1000_pages']:7.2f} {data['coverage']:6.3f} "
            f"{data['abstention_rate']:6.3f} {data['selective_error_rate']:8.3f} "
            f"{data['severe_errors_avoided']:8d} "
            f"{data['fisher_exact_p_accepted_vs_abstained']:8.4f}"
        )
    print("\ncomplementarity:")
    for key, value in complementarity.items():
        if key != "reading":
            print(f"  {key}: {value}")
    print(f"\nreceipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
