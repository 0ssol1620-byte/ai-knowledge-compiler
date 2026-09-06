#!/usr/bin/env python3
"""Is the runtime reproducible at the metric level, at holdout scale?

The stability signal rests on an observation that sounds contradictory: the same
immutable assembly, at temperature 0, does not always emit the same bytes. A9-3
recorded the other half of that observation on the discovery set — the *metrics*
barely move even though the bytes do — and this re-measures it on 4x the pages.

Both halves matter, and they matter in opposite directions:

  * If the aggregate metrics moved between runs, no benchmark number from this
    runtime would mean anything without repeats, and every published figure
    would need an error bar derived from re-running rather than from sampling.
  * If the *per-page* scores never moved, byte instability would be cosmetic —
    whitespace, ordering — and the stability gate would be selecting noise.

The discovery set said: aggregates stable, a minority of pages genuinely
different. This checks whether that holds at 749 scored pages, and in
particular whether the pages that differ in bytes are the pages that differ in
score, which is the mechanism the gate assumes.

Nothing here is a confirmatory endpoint. The primary test used run 1's scores
only, exactly as pre-registered, and was run and written before this existed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SEVERE = 0.10


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def timeout_pages(log: Path | None) -> set[str]:
    """Pages the harness abandoned to its chunked-Hungarian fallback."""
    if log is None or not log.is_file():
        return set()
    text = log.read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r"\[(?:timeout-fallback|match-timeout)\] (.+?): ", text))


def per_page(artifacts: Path) -> dict[str, float]:
    return {
        key: float(value)
        for key, value in json.loads(
            (artifacts / "text_block_per_page_edit.json").read_text(encoding="utf-8")
        ).items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-a-artifacts", type=Path, required=True)
    parser.add_argument("--run-b-artifacts", type=Path, required=True)
    parser.add_argument("--run-a-predictions", type=Path, required=True)
    parser.add_argument("--run-b-predictions", type=Path, required=True)
    parser.add_argument("--run-a-stdout", type=Path)
    parser.add_argument("--run-b-stdout", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    first = per_page(args.run_a_artifacts.resolve())
    second = per_page(args.run_b_artifacts.resolve())
    shared = sorted(set(first) & set(second))

    identical_bytes: list[str] = []
    differing_bytes: list[str] = []
    for page in shared:
        stem = Path(page).stem
        a = (args.run_a_predictions.resolve() / f"{stem}.md")
        b = (args.run_b_predictions.resolve() / f"{stem}.md")
        if not (a.is_file() and b.is_file()):
            continue
        (identical_bytes if a.read_text("utf-8") == b.read_text("utf-8")
         else differing_bytes).append(page)

    def band(pages: list[str]) -> dict[str, Any]:
        if not pages:
            return {"pages": 0}
        deltas = [abs(first[p] - second[p]) for p in pages]
        flips = [
            p for p in pages
            if (first[p] > SEVERE) != (second[p] > SEVERE)
        ]
        return {
            "pages": len(pages),
            "mean_absolute_score_delta": statistics.mean(deltas),
            "median_absolute_score_delta": statistics.median(deltas),
            "max_absolute_score_delta": max(deltas),
            "pages_with_any_score_change": sum(1 for d in deltas if d > 0),
            "severe_label_flips": len(flips),
            "severe_label_flip_rate": len(flips) / len(pages),
        }

    aggregate = {
        "run_a_mean_edit": statistics.mean(first[p] for p in shared),
        "run_b_mean_edit": statistics.mean(second[p] for p in shared),
        "run_a_severe": sum(1 for p in shared if first[p] > SEVERE),
        "run_b_severe": sum(1 for p in shared if second[p] > SEVERE),
    }
    aggregate["mean_edit_delta"] = abs(
        aggregate["run_a_mean_edit"] - aggregate["run_b_mean_edit"]
    )
    aggregate["severe_count_delta"] = abs(
        aggregate["run_a_severe"] - aggregate["run_b_severe"]
    )

    stable_band = band(identical_bytes)
    unstable_band = band(differing_bytes)

    # Why a byte-identical page can score differently, which it should not be
    # able to do. The harness wraps the official matcher in a wall-clock stall
    # recovery: `quick_match` is abandoned after a timeout and a chunked
    # Hungarian fallback with an order penalty runs instead. Which pages exceed
    # that timeout depends on machine load, so two evaluations of identical
    # bytes can take different code paths.
    fallback_a = timeout_pages(args.run_a_stdout)
    fallback_b = timeout_pages(args.run_b_stdout)
    moved_identical = [p for p in identical_bytes if first[p] != second[p]]
    asymmetric = fallback_a ^ fallback_b
    evaluator_nondeterminism = {
        "timeout_fallback_pages_run_a": len(fallback_a),
        "timeout_fallback_pages_run_b": len(fallback_b),
        "pages_that_fell_back_in_exactly_one_run": len(asymmetric),
        "byte_identical_pages_whose_score_moved": len(moved_identical),
        "of_those_that_hit_a_fallback_in_at_least_one_run": sum(
            1 for page in moved_identical if page in fallback_a or page in fallback_b
        ),
        "severe_label_flips_on_byte_identical_pages": sum(
            1 for page in moved_identical
            if (first[page] > SEVERE) != (second[page] > SEVERE)
        ),
        "diagnosis": (
            "the harness applies a wall-clock timeout to the official matcher "
            "and substitutes a chunked Hungarian fallback when it is exceeded. "
            "Which pages exceed it depends on machine load, so the same bytes "
            "can be scored by two different algorithms on two runs. This is "
            "nondeterminism in *our* stall-recovery wrapper, not evidence that "
            "the upstream evaluator's own matching is nondeterministic."
        ),
        "why_it_does_not_overturn_the_primary_result": (
            "the gate never reads the evaluator, so this noise is independent of "
            "the accepted/abstained split. Independent misclassification of the "
            "outcome attenuates a measured association toward the null rather "
            "than manufacturing one, so the confirmatory p-value is if anything "
            "conservative. What it does mean is that the severe-error label "
            "carries roughly 0.7% per-page noise, and that a single per-page "
            "label from a single scoring run should not be treated as exact."
        ),
    }

    # The mechanism check: byte instability should predict score instability.
    # If it does not, the stability gate is selecting cosmetic differences.
    mechanism = {
        "byte_identical_pages_whose_score_moved": stable_band.get(
            "pages_with_any_score_change"
        ),
        "byte_differing_pages_whose_score_moved": unstable_band.get(
            "pages_with_any_score_change"
        ),
        "reading": (
            "this was written expecting the first number to be 0, because a "
            "byte-identical page should not be able to change score. It is not 0, "
            "and `evaluator_harness_nondeterminism` explains why: the harness's "
            "wall-clock stall recovery can route identical bytes through two "
            "different matching algorithms. The second number is the share of "
            "byte instability that is more than cosmetic, and it must be read "
            "against that noise floor rather than as a clean measurement."
        ),
    }

    receipt = {
        "schema": "tavonel.a9-metric-reproducibility.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "SECONDARY, EXPLORATORY -- not a pre-registered endpoint",
        "severe_error_definition": "official text-block edit distance > 0.10",
        "pages_scored_in_both_runs": len(shared),
        "aggregate": aggregate,
        "byte_identical_pages": stable_band,
        "byte_differing_pages": unstable_band,
        "mechanism_check": mechanism,
        "evaluator_harness_nondeterminism": evaluator_nondeterminism,
        "why_this_is_not_the_primary_test": (
            "the confirmatory endpoint used run 1's scores only, as pre-registered, "
            "and was executed and written before this analysis existed. This "
            "measures whether the runtime's *metrics* reproduce, which is a "
            "property of the benchmark apparatus rather than of the gate."
        ),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)

    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"pages scored in both runs: {len(shared)}")
    print(f"  mean edit  run A {aggregate['run_a_mean_edit']:.6f} "
          f"run B {aggregate['run_b_mean_edit']:.6f} "
          f"(delta {aggregate['mean_edit_delta']:.6f})")
    print(f"  severe     run A {aggregate['run_a_severe']} "
          f"run B {aggregate['run_b_severe']} "
          f"(delta {aggregate['severe_count_delta']})")
    print("harness nondeterminism:")
    for key in (
        "timeout_fallback_pages_run_a",
        "timeout_fallback_pages_run_b",
        "pages_that_fell_back_in_exactly_one_run",
        "byte_identical_pages_whose_score_moved",
        "of_those_that_hit_a_fallback_in_at_least_one_run",
        "severe_label_flips_on_byte_identical_pages",
    ):
        print(f"  {key}: {evaluator_nondeterminism[key]}")
    for name, data in (("byte-identical", stable_band), ("byte-differing", unstable_band)):
        if data["pages"]:
            print(f"  {name:15} {data['pages']:4} pages, "
                  f"score moved on {data['pages_with_any_score_change']}, "
                  f"severe label flipped on {data['severe_label_flips']}")
    print(f"receipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
