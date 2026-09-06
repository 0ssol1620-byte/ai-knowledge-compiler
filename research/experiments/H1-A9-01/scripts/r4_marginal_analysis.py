#!/usr/bin/env python3
"""R4, second pass: what does each additional dollar of gating actually buy?

The first pass answered "which gate is best", which is the wrong question. Every
gate here abstains on a different set of pages and costs a different amount, so
the useful question is **at what cost level does which combination become
worth it**. This file reports the marginal quantities that answer that:

  * absolute and relative risk reduction against the ungated baseline
  * severe errors avoided per 1,000 pages
  * incremental dollars per severe error avoided, against the next cheapest tier
  * error reduction per additional percentage point of abstention
  * the marginal gain of agreement over stability, and of adding agreement to
    stability -- which are different numbers and are reported separately

One instrument change since the first pass, and it matters. `evidence_validity`
was reported as the strongest and cheapest signal at p = 0.0014. It was
measuring the corpus's typesetting: `orphan_currency` fired on the opening `$`
of LaTeX math spans, which this corpus uses for prices, so the flag tracked
formula-dense pages, and formula-dense pages are harder. With math spans
excluded the same instrument flags 6 pages instead of 17 and reaches p = 0.0442,
it detects none of the nine semantic corruptions injected against it, and it
fires on 8.5% of human-annotated ground-truth documents against 3% of model
outputs. It is carried below as a measured configuration and is **not** a
candidate for the confirmatory primary signal.

Everything here is exploratory. Operating points were chosen after seeing this
corpus and the p-values are not corrected for that.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from akc_cir.critical_tokens import verify_critical_tokens  # noqa: E402
from evaluator_aligned_instruments import page_structural_flag  # noqa: E402
from holdout_power_calculation import fisher_exact_two_sided  # noqa: E402
from repaired_output_instruments import evidence_validity  # noqa: E402

SEVERE = 0.10


def gate_metrics(
    pages: list[dict[str, Any]],
    accepted: list[dict[str, Any]],
    baseline_rate: float,
    gpu_seconds: float,
    usd_per_1000: float,
) -> dict[str, Any]:
    total = len(pages)
    accepted_ids = {p["image_path"] for p in accepted}
    abstained = [p for p in pages if p["image_path"] not in accepted_ids]
    accepted_bad = sum(1 for p in accepted if p["severe"])
    abstained_bad = sum(1 for p in abstained if p["severe"])
    selective = accepted_bad / len(accepted) if accepted else 0.0
    abstention = len(abstained) / total

    absolute_reduction = baseline_rate - selective
    relative_reduction = absolute_reduction / baseline_rate if baseline_rate else 0.0
    # Avoided errors are counted over the pages that still get processed, which
    # is what a buyer of 1,000 pages of throughput actually experiences.
    avoided_per_1000 = absolute_reduction * 1000.0

    return {
        "gpu_seconds_per_page": gpu_seconds,
        "usd_per_1000_pages": usd_per_1000,
        "coverage": len(accepted) / total,
        "abstention_rate": abstention,
        "accepted_pages": len(accepted),
        "selective_severe_error_rate": selective,
        "errors_accepted": accepted_bad,
        "errors_abstained": abstained_bad,
        "absolute_risk_reduction": absolute_reduction,
        "relative_risk_reduction": relative_reduction,
        "severe_errors_avoided_per_1000_pages": avoided_per_1000,
        "error_reduction_per_abstention_point": (
            absolute_reduction / (abstention * 100.0) if abstention else None
        ),
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

    edit = json.loads(
        (args.run_a_artifacts.resolve() / "text_block_per_page_edit.json").read_text(
            encoding="utf-8"
        )
    )
    samples = json.loads(args.ground_truth.resolve().read_text(encoding="utf-8"))
    receipt_a = json.loads(args.run_a_receipt.resolve().read_text(encoding="utf-8"))
    receipt_b = json.loads(args.run_b_receipt.resolve().read_text(encoding="utf-8"))
    mineru = json.loads(args.second_parser_cost.resolve().read_text(encoding="utf-8"))

    pages: list[dict[str, Any]] = []
    for sample in samples:
        image = str(sample["page_info"]["image_path"])
        if image not in edit:
            continue
        stem = Path(image).stem
        first = (args.run_a_predictions.resolve() / f"{stem}.md").read_text("utf-8")
        second = (args.run_b_predictions.resolve() / f"{stem}.md").read_text("utf-8")

        # Amendment 01: a page the agreement half cannot evaluate is abstained,
        # never accepted. On the discovery set every page had a second-parser
        # prediction and this branch was unreachable; on the holdout 15 do not,
        # and reading the file unconditionally raised FileNotFoundError. Treating
        # a missing prediction as agreement would have been the dangerous fix --
        # it would silently accept exactly the pages with the least evidence, and
        # it would disagree with what the confirmatory test does.
        other_path = args.second_parser_predictions.resolve() / f"{stem}.md"
        if other_path.is_file():
            mismatches = len(
                verify_critical_tokens(first, other_path.read_text("utf-8")).mismatches
            )
            second_parser_available = True
        else:
            mismatches = None
            second_parser_available = False

        pages.append(
            {
                "image_path": image,
                "stable": first == second,
                "agreement": 0.0 if mismatches is None else 1.0 / (1.0 + mismatches),
                "second_parser_available": second_parser_available,
                "cross_parser_mismatches": mismatches,
                "evidence_flag": evidence_validity(first) < 1.0,
                "structural_flag": page_structural_flag(first)["structurally_defective"],
                "severe": float(edit[image]) > SEVERE,
                "official_text_edit": float(edit[image]),
            }
        )

    total = len(pages)
    baseline_bad = sum(1 for p in pages if p["severe"])
    baseline_rate = baseline_bad / total

    ovis_per_page = statistics.mean(
        [
            float(receipt_a["inference_seconds"]) / 200.0,
            float(receipt_b["inference_seconds"]) / 200.0,
        ]
    )
    ovis_rate = 0.34
    mineru_per_page = 3600.0 / float(mineru["healthy_worker_only"]["pages_per_pod_hour"])
    mineru_rate = float(mineru["hourly_rate_usd"])

    def usd(seconds: float, rate: float) -> float:
        return seconds / 3600.0 * rate * 1000.0

    # The agreement gate is evaluated at the stability gate's coverage so the
    # two are compared at matched abstention rather than at each one's most
    # flattering operating point.
    stable = [p for p in pages if p["stable"]]
    target_coverage = len(stable) / total
    by_agreement = sorted(pages, key=lambda p: -p["agreement"])
    keep = round(target_coverage * total)
    agreement_floor = by_agreement[keep - 1]["agreement"]
    agreeing = [p for p in pages if p["agreement"] >= agreement_floor]

    configurations = {
        "single_run": (
            pages,
            ovis_per_page,
            usd(ovis_per_page, ovis_rate),
            "one pass, accept everything",
        ),
        "evidence_validity_gate": (
            [p for p in pages if not p["evidence_flag"]],
            ovis_per_page,
            usd(ovis_per_page, ovis_rate),
            "one pass; abstain on internally malformed output (corrected instrument)",
        ),
        "structural_gate": (
            [p for p in pages if not p["structural_flag"]],
            ovis_per_page,
            usd(ovis_per_page, ovis_rate),
            "one pass; abstain on a structurally defective table",
        ),
        "stability_gate": (
            stable,
            2 * ovis_per_page,
            usd(2 * ovis_per_page, ovis_rate),
            "two passes of the same parser; abstain where they differ",
        ),
        "agreement_gate_matched_coverage": (
            agreeing,
            ovis_per_page + mineru_per_page,
            usd(ovis_per_page, ovis_rate) + usd(mineru_per_page, mineru_rate),
            "second parser; abstain on low critical-token agreement",
        ),
        "stability_and_agreement": (
            [p for p in stable if p["agreement"] >= agreement_floor],
            2 * ovis_per_page + mineru_per_page,
            usd(2 * ovis_per_page, ovis_rate) + usd(mineru_per_page, mineru_rate),
            "both; abstain if either fires",
        ),
    }

    results = {
        name: {
            "description": description,
            **gate_metrics(pages, accepted, baseline_rate, seconds, dollars),
        }
        for name, (accepted, seconds, dollars, description) in configurations.items()
    }

    # --- incremental cost per severe error avoided --------------------------
    # Each tier is compared with the next cheapest tier, not with the baseline:
    # what a buyer decides is whether to spend the *next* increment.
    ordered = sorted(results.items(), key=lambda kv: kv[1]["usd_per_1000_pages"])
    incremental = []
    for index in range(1, len(ordered)):
        name, gate = ordered[index]
        prior_name, prior = ordered[index - 1]
        delta_usd = gate["usd_per_1000_pages"] - prior["usd_per_1000_pages"]
        delta_avoided = (
            gate["severe_errors_avoided_per_1000_pages"]
            - prior["severe_errors_avoided_per_1000_pages"]
        )
        incremental.append(
            {
                "configuration": name,
                "compared_with": prior_name,
                "additional_usd_per_1000_pages": delta_usd,
                "additional_severe_errors_avoided_per_1000_pages": delta_avoided,
                "usd_per_additional_severe_error_avoided": (
                    delta_usd / delta_avoided if delta_avoided > 0 else None
                ),
                "dominated": delta_avoided <= 0,
            }
        )

    # --- signal-level marginal gains ---------------------------------------
    severe = {p["image_path"] for p in pages if p["severe"]}
    unstable = {p["image_path"] for p in pages if not p["stable"]}
    low_agreement = {p["image_path"] for p in pages if p["agreement"] < agreement_floor}
    evidence = {p["image_path"] for p in pages if p["evidence_flag"]}
    structural = {p["image_path"] for p in pages if p["structural_flag"]}

    def caught(flags: set[str]) -> int:
        return len(flags & severe)

    marginal = {
        "severe_errors_total": len(severe),
        "caught_by_stability": caught(unstable),
        "caught_by_agreement": caught(low_agreement),
        "caught_by_evidence": caught(evidence),
        "caught_by_structural": caught(structural),
        "agreement_marginal_gain_over_stability": caught(low_agreement - unstable),
        "stability_marginal_gain_over_agreement": caught(unstable - low_agreement),
        "adding_agreement_to_stability": caught(unstable | low_agreement)
        - caught(unstable),
        "adding_stability_to_agreement": caught(unstable | low_agreement)
        - caught(low_agreement),
        "caught_by_any_signal": caught(unstable | low_agreement | evidence | structural),
        "caught_by_no_signal": len(
            severe - unstable - low_agreement - evidence - structural
        ),
        "missed_by_stability_and_agreement": sorted(severe - unstable - low_agreement),
        "jaccard_stability_agreement": (
            len(unstable & low_agreement) / len(unstable | low_agreement)
            if (unstable | low_agreement)
            else None
        ),
    }

    receipt = {
        "schema": "tavonel.a9-r4-marginal.v2",
        "status": "EXPLORATORY",
        "page_count": total,
        "baseline_severe_error_rate": baseline_rate,
        "severe_error_definition": "official text-block edit distance > 0.10",
        "instrument_correction": (
            "evidence_validity now excludes LaTeX math spans; the previous "
            "p = 0.0014 was driven by math delimiters being read as currency "
            "symbols and is retracted"
        ),
        "cost_basis": {
            "ovis_gpu_seconds_per_page": ovis_per_page,
            "ovis_hourly_rate_usd": ovis_rate,
            "mineru_gpu_seconds_per_page": mineru_per_page,
            "mineru_hourly_rate_usd": mineru_rate,
            "note": (
                "the two parsers were measured on different clouds at different "
                "hourly rates, so GPU-seconds is the comparable quantity and "
                "dollars are reported with each rate named"
            ),
        },
        "configurations": results,
        "incremental_cost_effectiveness": incremental,
        "signal_marginal_gains": marginal,
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    header = (
        f"{'configuration':34}{'$/1k':>7}{'cov':>7}{'sel err':>9}"
        f"{'ARR':>8}{'RRR':>7}{'avoid/1k':>10}{'per pt':>8}{'p':>8}"
    )
    print(f"baseline severe error rate: {baseline_rate:.4f} ({baseline_bad}/{total})\n")
    print(header)
    for name, gate in results.items():
        per_point = gate["error_reduction_per_abstention_point"]
        print(
            f"{name:34}{gate['usd_per_1000_pages']:>7.2f}{gate['coverage']:>7.3f}"
            f"{gate['selective_severe_error_rate']:>9.4f}"
            f"{gate['absolute_risk_reduction']:>8.4f}"
            f"{gate['relative_risk_reduction']:>7.2f}"
            f"{gate['severe_errors_avoided_per_1000_pages']:>10.1f}"
            f"{('  n/a' if per_point is None else f'{per_point:.4f}'):>8}"
            f"{gate['fisher_exact_p_accepted_vs_abstained']:>8.4f}"
        )

    print("\nincremental, each tier against the next cheapest:")
    for step in incremental:
        cost = step["usd_per_additional_severe_error_avoided"]
        if step["dominated"]:
            shown = "dominated"
        elif step["additional_usd_per_1000_pages"] <= 0:
            shown = "free"
        else:
            shown = f"${cost:.3f}/error"
        print(
            f"  {step['configuration']:34} vs {step['compared_with']:30} "
            f"+${step['additional_usd_per_1000_pages']:.2f}/1k  "
            f"+{step['additional_severe_errors_avoided_per_1000_pages']:.1f} avoided  "
            f"{shown}"
        )

    print("\nsignal marginal gains (severe errors caught):")
    for key, value in marginal.items():
        if key.startswith("missed_by"):
            print(f"  {key}: {len(value)}")
            continue
        print(f"  {key}: {value}")
    print(f"\nreceipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
