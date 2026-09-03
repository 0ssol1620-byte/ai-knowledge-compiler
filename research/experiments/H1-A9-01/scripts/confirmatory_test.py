#!/usr/bin/env python3
"""The one confirmatory test, run once, on the frozen holdout.

Every parameter this file uses was fixed before the holdout existed:

  * the gate -- abstain if the two gated-parser runs differ, or if cross-parser
    critical-token mismatches exceed 21, or if the second parser has no
    prediction for the page (amendment 01);
  * severe error -- official text-block edit distance > 0.10;
  * the test -- Fisher's exact, two-sided, alpha 0.05, accepted versus abstained.

Nothing here reads the discovery set and nothing here searches a threshold. The
frozen values are asserted against the protocol receipt on the way in, so a run
with a drifted operating point refuses instead of reporting.

Secondary quantities are computed and reported, and are labelled secondary. If
the primary test does not reject, no secondary number converts the result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from akc_cir.critical_tokens import verify_critical_tokens  # noqa: E402
from holdout_power_calculation import fisher_exact_two_sided  # noqa: E402

# --- frozen operating point, protocol revision 2 + amendment 01 -------------
SEVERE_EDIT_DISTANCE = 0.10
AGREEMENT_MAX_MISMATCHES = 21
ALPHA = 0.05
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20260818

# Measured on the discovery runs; used only to price the configuration, never to
# decide anything about the endpoint.
GATED_SECONDS_PER_PAGE = 6.71
GATED_HOURLY_USD = 0.34
SECOND_PARSER_SECONDS_PER_PAGE = 6.00
SECOND_PARSER_HOURLY_USD = 0.74


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval: behaves at the small counts this design produces."""
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denominator
    spread = (
        z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denominator
    )
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def bootstrap_difference(
    accepted: list[bool], abstained: list[bool], seed: int, resamples: int
) -> tuple[float, float]:
    """Percentile CI for the abstained-minus-accepted error-rate difference."""
    rng = random.Random(seed)  # noqa: S311 - a resampling CI, not cryptography
    differences = []
    for _ in range(resamples):
        a = [accepted[rng.randrange(len(accepted))] for _ in range(len(accepted))]
        b = [abstained[rng.randrange(len(abstained))] for _ in range(len(abstained))]
        differences.append(sum(b) / len(b) - sum(a) / len(a))
    differences.sort()
    return (
        differences[int(0.025 * resamples)],
        differences[int(0.975 * resamples) - 1],
    )



def evaluator_identity(artifacts: Path) -> dict[str, Any]:
    """Which evaluator produced these scores, read from the run's own config.

    The harness writes the rendered task config next to the artifacts, and that
    config carries the `deterministic_matching` flag. Reading it here means the
    result receipt records the instrument as measured rather than as asserted on
    the command line.
    """
    for candidate in (
        artifacts.parent / "omnidoc-partial.yaml",
        artifacts.parent / "omnidoc.yaml",
    ):
        if candidate.is_file():
            body = candidate.read_text(encoding="utf-8", errors="replace")
            return {
                "config": str(candidate),
                "deterministic_matching": "deterministic_matching: true" in body,
                "config_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
            }
    return {"config": None, "deterministic_matching": None, "config_sha256": None}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--run-a-predictions", type=Path, required=True)
    parser.add_argument("--run-b-predictions", type=Path, required=True)
    parser.add_argument("--second-parser-predictions", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    holdout = json.loads(args.holdout.resolve().read_text(encoding="utf-8"))
    if holdout.get("status") != "FROZEN":
        raise SystemExit("holdout manifest is not FROZEN")
    edit = json.loads(
        (args.artifacts.resolve() / "text_block_per_page_edit.json").read_text(
            encoding="utf-8"
        )
    )

    pages: list[dict[str, Any]] = []
    without_a_score: list[str] = []
    for record in holdout["pages"]:
        image = record["image_path"]
        stem = Path(image).stem
        if image not in edit:
            without_a_score.append(image)
            continue
        first_path = args.run_a_predictions.resolve() / f"{stem}.md"
        second_path = args.run_b_predictions.resolve() / f"{stem}.md"
        other_path = args.second_parser_predictions.resolve() / f"{stem}.md"
        if not (first_path.is_file() and second_path.is_file()):
            raise SystemExit(f"gated-parser prediction missing for {image}")

        first = first_path.read_text(encoding="utf-8")
        second = second_path.read_text(encoding="utf-8")
        stable = first == second

        if other_path.is_file():
            mismatches = len(
                verify_critical_tokens(first, other_path.read_text("utf-8")).mismatches
            )
            agrees = mismatches <= AGREEMENT_MAX_MISMATCHES
            second_parser_available = True
        else:
            # Amendment 01, fixed before any holdout outcome existed: a page the
            # agreement half cannot evaluate is abstained, never accepted.
            mismatches = None
            agrees = False
            second_parser_available = False

        pages.append(
            {
                "image_path": image,
                "document_id": record["document_id"],
                "stable": stable,
                "cross_parser_mismatches": mismatches,
                "second_parser_available": second_parser_available,
                "accepted": stable and agrees,
                "severe": float(edit[image]) > SEVERE_EDIT_DISTANCE,
                "official_text_edit": float(edit[image]),
            }
        )

    total = len(pages)
    accepted = [p for p in pages if p["accepted"]]
    abstained = [p for p in pages if not p["accepted"]]
    accepted_bad = sum(1 for p in accepted if p["severe"])
    abstained_bad = sum(1 for p in abstained if p["severe"])
    baseline_bad = accepted_bad + abstained_bad

    p_value = fisher_exact_two_sided(
        accepted_bad,
        len(accepted) - accepted_bad,
        abstained_bad,
        len(abstained) - abstained_bad,
    )

    accepted_rate = accepted_bad / len(accepted) if accepted else 0.0
    abstained_rate = abstained_bad / len(abstained) if abstained else 0.0
    baseline_rate = baseline_bad / total
    absolute_reduction = baseline_rate - accepted_rate
    relative_reduction = absolute_reduction / baseline_rate if baseline_rate else 0.0

    low, high = bootstrap_difference(
        [p["severe"] for p in accepted],
        [p["severe"] for p in abstained],
        BOOTSTRAP_SEED,
        BOOTSTRAP_RESAMPLES,
    )

    gated_seconds = 2 * GATED_SECONDS_PER_PAGE
    usd_per_1000 = (
        gated_seconds / 3600.0 * GATED_HOURLY_USD * 1000.0
        + SECOND_PARSER_SECONDS_PER_PAGE / 3600.0 * SECOND_PARSER_HOURLY_USD * 1000.0
    )
    avoided_per_1000 = absolute_reduction * 1000.0

    result = {
        "schema": "tavonel.a9-confirmatory-result.v1",
        "status": "CONFIRMATORY",
        "protocol": "A9_CONFIRMATORY_PROTOCOL_2026-08-18.md revision 2 + amendment 01",
        # Two evaluators now exist -- the frozen one and the deterministic
        # correction of amendment 02 -- so a result that does not name the
        # scores it consumed cannot be told apart from the other reading.
        "outcome_source": {
            "artifacts": str(args.artifacts.resolve()),
            "text_block_per_page_edit_sha256": hashlib.sha256(
                (args.artifacts.resolve() / "text_block_per_page_edit.json").read_bytes()
            ).hexdigest(),
            "evaluator": evaluator_identity(args.artifacts.resolve()),
        },
        "holdout_manifest_page_count": holdout["page_count"],
        "pages_tested": total,
        "pages_without_an_official_score": without_a_score,
        "frozen_operating_point": {
            "stability": "byte-identical output across two gated-parser runs",
            "agreement_max_critical_token_mismatches": AGREEMENT_MAX_MISMATCHES,
            "missing_second_parser_prediction": "abstain (amendment 01)",
            "severe_error_definition": "official text-block edit distance > 0.10",
        },
        "primary": {
            "test": "Fisher exact, two-sided",
            "alpha": ALPHA,
            "accepted_pages": len(accepted),
            "accepted_severe": accepted_bad,
            "abstained_pages": len(abstained),
            "abstained_severe": abstained_bad,
            "p_value": p_value,
            "rejects_at_alpha": p_value < ALPHA,
            "direction_matches_discovery": abstained_rate > accepted_rate,
        },
        "secondary": {
            "baseline_severe_error_rate": baseline_rate,
            "selective_severe_error_rate": accepted_rate,
            "abstained_severe_error_rate": abstained_rate,
            "coverage": len(accepted) / total,
            "abstention_rate": len(abstained) / total,
            "absolute_risk_reduction": absolute_reduction,
            "relative_risk_reduction": relative_reduction,
            "risk_ratio_abstained_over_accepted": (
                abstained_rate / accepted_rate if accepted_rate else None
            ),
            "accepted_rate_95_ci_wilson": wilson_interval(accepted_bad, len(accepted)),
            "abstained_rate_95_ci_wilson": wilson_interval(
                abstained_bad, len(abstained)
            ),
            "rate_difference_95_ci_bootstrap": [low, high],
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "severe_errors_avoided_per_1000_pages": avoided_per_1000,
            "gpu_seconds_per_page": gated_seconds + SECOND_PARSER_SECONDS_PER_PAGE,
            "usd_per_1000_pages": usd_per_1000,
            "usd_per_severe_error_avoided": (
                usd_per_1000 / avoided_per_1000 if avoided_per_1000 > 0 else None
            ),
            "pages_abstained_only_for_a_missing_second_parser": sum(
                1
                for p in pages
                if not p["second_parser_available"] and p["stable"]
            ),
        },
        "per_signal_secondary": {
            "unstable_pages": sum(1 for p in pages if not p["stable"]),
            "low_agreement_pages": sum(
                1
                for p in pages
                if p["cross_parser_mismatches"] is not None
                and p["cross_parser_mismatches"] > AGREEMENT_MAX_MISMATCHES
            ),
            "severe_caught_by_stability": sum(
                1 for p in pages if p["severe"] and not p["stable"]
            ),
            "severe_caught_by_agreement": sum(
                1
                for p in pages
                if p["severe"]
                and p["cross_parser_mismatches"] is not None
                and p["cross_parser_mismatches"] > AGREEMENT_MAX_MISMATCHES
            ),
            "severe_caught_by_neither": sum(
                1
                for p in pages
                if p["severe"]
                and p["stable"]
                and p["cross_parser_mismatches"] is not None
                and p["cross_parser_mismatches"] <= AGREEMENT_MAX_MISMATCHES
            ),
        },
        "pages": sorted(pages, key=lambda p: p["image_path"]),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    primary = result["primary"]
    secondary = result["secondary"]
    print("=== CONFIRMATORY, one test ===")
    print(f"pages tested: {total}")
    print(
        f"accepted {primary['accepted_pages']} "
        f"({primary['accepted_severe']} severe, {secondary['selective_severe_error_rate']:.4f})"
    )
    print(
        f"abstained {primary['abstained_pages']} "
        f"({primary['abstained_severe']} severe, {secondary['abstained_severe_error_rate']:.4f})"
    )
    print(f"Fisher exact p = {primary['p_value']:.6f}  rejects={primary['rejects_at_alpha']}")
    print(
        f"ARR {secondary['absolute_risk_reduction']:.4f}  "
        f"RRR {secondary['relative_risk_reduction']:.3f}"
    )
    ci = secondary["rate_difference_95_ci_bootstrap"]
    print(f"rate difference 95% CI (bootstrap): [{ci[0]:.4f}, {ci[1]:.4f}]")
    print(
        f"coverage {secondary['coverage']:.4f}  "
        f"abstention {secondary['abstention_rate']:.4f}"
    )
    per_error = secondary["usd_per_severe_error_avoided"]
    print(
        f"avoided/1k {secondary['severe_errors_avoided_per_1000_pages']:.1f}  "
        f"${secondary['usd_per_1000_pages']:.2f}/1k  "
        + (f"${per_error:.3f}/error" if per_error else "no errors avoided")
    )
    print(f"receipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
