#!/usr/bin/env python3
"""A9 minimal: is two-parser agreement a selective-acceptance signal, or noise?

Phase 0 found that on the only cases with two independent parsers, the
source-grounded arm cannot run -- the sources are scans with no native text. It
did not find that nothing can be measured. Two arms *are* available on those 200
cases, agreement and abstain, and this measures them.

The question is sharper than "does agreement correlate with quality". A signal
that correlates with error but does not concentrate it is useless for gating:
you abstain on a random-ish slice, pay coverage, and buy no precision. So this
reports the thing a gate is actually judged on -- a coverage/risk curve -- and
compares every operating point against processing everything, which is the
policy a gate has to beat.

Design, and the reasons for it:

  * **Agreement is computed from the two outputs alone.** No ground truth enters
    the signal. A gate that needed the answer to decide whether to accept the
    answer could not run at inference time.

  * **Correctness comes from a separately frozen evaluator**, the official
    OmniDocBench per-page metric, run on both parsers under one evaluator
    revision, one config and one ground-truth file. That is the preregistration's
    anti-circularity rule, and it is also why the second parser was re-scored on
    the 200-page subset instead of reusing its 1,651-page evaluation.

  * **Error is defined before the curve is drawn**, at several thresholds, and
    every threshold is reported. No threshold in this repository is calibrated.

  * **The baseline is coverage 1.0**, not another gate. "Accept everything" is
    what the product does today, and a gate that does not beat it is not worth
    its abstentions.

Confidence intervals are bootstrap over pages, because pages are the unit that
was sampled. They are not a claim about other corpora.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import random
import re
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.critical_tokens import verify_critical_tokens  # noqa: E402

# Error thresholds on the official per-page text edit distance. Reported as a
# family, never one "the" threshold.
ERROR_THRESHOLDS = (0.02, 0.05, 0.10, 0.20)
# Operating points for the gate, as agreement quantiles so the curve is defined
# by the data rather than by a number chosen after seeing it.
COVERAGE_POINTS = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1)
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 20260818

WHITESPACE = re.compile(r"\s+")
NUMERIC = re.compile(r"[\d][\d,.]*")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def normalise(text: str) -> str:
    return WHITESPACE.sub(" ", text).strip().lower()


def text_agreement(left: str, right: str) -> float:
    """Similarity of the two parsers' text, with no ground truth involved."""
    return difflib.SequenceMatcher(None, normalise(left), normalise(right)).ratio()


def numeric_agreement(left: str, right: str) -> float:
    """Jaccard over the numbers each parser read off the page.

    Text similarity is dominated by prose, which is the part both parsers get
    right. Numbers are where the disagreement that matters lives.
    """
    a = {n.replace(",", "") for n in NUMERIC.findall(left)}
    b = {n.replace(",", "") for n in NUMERIC.findall(right)}
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def critical_token_agreement(left: str, right: str) -> float:
    """1.0 when neither parser's critical tokens contradict the other's.

    Uses the same verifier the corruption measurement uses, but symmetrically and
    between the two candidates -- never against ground truth.
    """
    forward = verify_critical_tokens(left, right)
    backward = verify_critical_tokens(right, left)
    mismatches = len(forward.mismatches) + len(backward.mismatches)
    return 1.0 / (1.0 + mismatches)


def load_per_page_edit(artifact_dir: Path) -> dict[str, float]:
    path = artifact_dir / "text_block_per_page_edit.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(page): float(value) for page, value in payload.items()}


def bootstrap_ci(
    values: list[float], statistic, samples: int = BOOTSTRAP_SAMPLES
) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(BOOTSTRAP_SEED)  # noqa: S311 -- resampling, not secrets
    size = len(values)
    draws = []
    for _ in range(samples):
        resample = [values[rng.randrange(size)] for _ in range(size)]
        draws.append(statistic(resample))
    draws.sort()
    lower = draws[int(0.025 * (samples - 1))]
    upper = draws[int(0.975 * (samples - 1))]
    return (lower, upper)


def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Exact p for a 2x2 table, so a small corpus is not over-claimed.

    Accepted and abstained pages are disjoint, so this is the comparison the
    curve actually licenses. Comparing the accepted subset's confidence interval
    with the whole corpus's would be comparing a set with a set that contains it.
    """
    rows = (a + b, c + d)
    cols = (a + c, b + d)
    total = a + b + c + d
    if total == 0 or 0 in rows or 0 in cols:
        return 1.0

    def probability(x: int) -> float:
        return (
            math.comb(cols[0], x)
            * math.comb(cols[1], rows[0] - x)
            / math.comb(total, rows[0])
        )

    observed = probability(a)
    low = max(0, rows[0] - cols[1])
    high = min(rows[0], cols[0])
    return min(
        1.0,
        sum(
            probability(x)
            for x in range(low, high + 1)
            if probability(x) <= observed + 1e-12
        ),
    )


def curve_for_threshold(
    pages: list[dict[str, Any]], signal: str, threshold: float
) -> list[dict[str, Any]]:
    """Accept the most-agreeing pages first; report risk at each coverage."""
    ordered = sorted(pages, key=lambda p: p[signal], reverse=True)
    total = len(ordered)
    rows = []
    for coverage in COVERAGE_POINTS:
        take = max(1, round(coverage * total))
        accepted = ordered[:take]
        abstained = ordered[take:]
        errors = [1.0 if p["error"][str(threshold)] else 0.0 for p in accepted]
        abstained_errors = [1.0 if p["error"][str(threshold)] else 0.0 for p in abstained]
        rate = statistics.mean(errors)
        low, high = bootstrap_ci(errors, statistics.mean)
        accepted_bad = int(sum(errors))
        abstained_bad = int(sum(abstained_errors))
        rows.append(
            {
                "target_coverage": coverage,
                "accepted_pages": take,
                "abstained_pages": total - take,
                "abstention_rate": (total - take) / total,
                "selective_error_rate": rate,
                "selective_error_rate_ci95": [low, high],
                "errors_accepted": accepted_bad,
                "errors_abstained": abstained_bad,
                "abstained_error_rate": (
                    statistics.mean(abstained_errors) if abstained_errors else None
                ),
                "fisher_exact_p_accepted_vs_abstained": fisher_exact_two_sided(
                    accepted_bad,
                    take - accepted_bad,
                    abstained_bad,
                    (total - take) - abstained_bad,
                ),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parser-a-name", required=True)
    parser.add_argument("--parser-a-predictions", type=Path, required=True)
    parser.add_argument("--parser-a-artifacts", type=Path, required=True)
    parser.add_argument("--parser-b-name", required=True)
    parser.add_argument("--parser-b-predictions", type=Path, required=True)
    parser.add_argument("--parser-b-artifacts", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    samples = json.loads(args.ground_truth.resolve().read_text(encoding="utf-8"))
    edit_a = load_per_page_edit(args.parser_a_artifacts.resolve())
    edit_b = load_per_page_edit(args.parser_b_artifacts.resolve())

    pages: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for sample in samples:
        image = str(sample["page_info"]["image_path"])
        stem = Path(image).stem
        text_a = (args.parser_a_predictions.resolve() / f"{stem}.md").read_text(
            encoding="utf-8"
        )
        text_b = (args.parser_b_predictions.resolve() / f"{stem}.md").read_text(
            encoding="utf-8"
        )
        if image not in edit_a or image not in edit_b:
            # The official evaluator emits a per-page text score only for pages
            # that had matched text blocks; a page that is entirely figure or
            # table has none. Such a page cannot be placed on a text-error curve
            # for either parser, so it is excluded -- and counted, because a
            # coverage curve that quietly shrinks its denominator is a coverage
            # curve about a different corpus.
            skipped.append(
                {
                    "image_path": image,
                    "scored_by_a": image in edit_a,
                    "scored_by_b": image in edit_b,
                }
            )
            continue
        page = {
            "image_path": image,
            "text_agreement": text_agreement(text_a, text_b),
            "numeric_agreement": numeric_agreement(text_a, text_b),
            "critical_token_agreement": critical_token_agreement(text_a, text_b),
            "edit_a": edit_a[image],
            "edit_b": edit_b[image],
            "error": {},
        }
        # The gated system's own output is parser A. Its correctness is what the
        # gate is accepting or abstaining on.
        for threshold in ERROR_THRESHOLDS:
            page["error"][str(threshold)] = edit_a[image] > threshold
        pages.append(page)

    signals = ("text_agreement", "numeric_agreement", "critical_token_agreement")
    analysis: dict[str, Any] = {}
    for threshold in ERROR_THRESHOLDS:
        key = str(threshold)
        errors = [1.0 if p["error"][key] else 0.0 for p in pages]
        base_rate = statistics.mean(errors)
        base_low, base_high = bootstrap_ci(errors, statistics.mean)
        per_signal = {}
        for signal in signals:
            # Does error concentrate where the parsers disagree? Split at the
            # median so the two halves are the same size and the comparison is
            # not an artifact of an unbalanced cut.
            median = statistics.median(p[signal] for p in pages)
            agree = [p for p in pages if p[signal] >= median]
            disagree = [p for p in pages if p[signal] < median]
            agree_rate = statistics.mean(1.0 if p["error"][key] else 0.0 for p in agree)
            disagree_rate = statistics.mean(
                1.0 if p["error"][key] else 0.0 for p in disagree
            )
            per_signal[signal] = {
                "median_split": median,
                "error_rate_high_agreement": agree_rate,
                "error_rate_low_agreement": disagree_rate,
                "concentration_ratio": (
                    disagree_rate / agree_rate if agree_rate else None
                ),
                "coverage_risk_curve": curve_for_threshold(pages, signal, threshold),
            }
        analysis[key] = {
            "error_threshold_text_edit_distance": threshold,
            "baseline_accept_everything": {
                "coverage": 1.0,
                "error_rate": base_rate,
                "error_rate_ci95": [base_low, base_high],
                "errors_accepted": int(sum(errors)),
            },
            "signals": per_signal,
        }

    receipt = {
        "schema": "tavonel.a9-selective-acceptance-two-parser.v1",
        "experiment_id": "H1-A9-01",
        "arms_evaluated": ["candidate_agreement_threshold", "abstain_review_baseline"],
        "arms_unavailable": {
            "model_self_confidence_threshold": "not emitted by either frozen runtime",
            "source_grounded_acceptance_receipt": "sources are scans with no native text",
        },
        "anti_circularity": (
            "agreement is computed from the two candidate outputs only; correctness "
            "comes from the official OmniDocBench evaluator run on both parsers under "
            "one evaluator revision, one config and one ground-truth file"
        ),
        "parsers": {
            "gated_system": args.parser_a_name,
            "second_opinion": args.parser_b_name,
        },
        "ground_truth_sha256": sha256_file(args.ground_truth.resolve()),
        "page_count": len(pages),
        "pages_in_corpus": len(samples),
        "pages_without_a_comparable_official_text_score": skipped,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "analysis": analysis,
        "pages": sorted(pages, key=lambda p: p["image_path"]),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    for threshold in ERROR_THRESHOLDS:
        block = analysis[str(threshold)]
        base = block["baseline_accept_everything"]["error_rate"]
        print(f"\n[a9] error = text edit distance > {threshold}", flush=True)
        print(f"[a9]   accept everything: error {base:.3f} at coverage 1.00", flush=True)
        for signal, data in block["signals"].items():
            ratio = data["concentration_ratio"]
            shown = f"{ratio:.2f}x" if ratio else "n/a"
            print(
                f"[a9]   {signal}: error {data['error_rate_high_agreement']:.3f} where "
                f"parsers agree vs {data['error_rate_low_agreement']:.3f} where they "
                f"disagree ({shown})",
                flush=True,
            )
    print(f"\n[a9] receipt: {args.output.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
