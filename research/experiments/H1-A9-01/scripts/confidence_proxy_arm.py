#!/usr/bin/env python3
"""Can anything observable stand in for a model confidence this runtime never emits?

The frozen Stage-1 runtime emits no per-case confidence, and the preregistration
forbids reconstructing one. That does not settle whether some *other* observable
separates good pages from bad ones -- it only settles that whatever does must be
called what it is. Nothing here is a model's self-confidence, and no receipt or
manuscript may present it as one.

Four candidate proxies, each scored the same way: split the corpus at the
proxy's median, compare the official error rate on either side, and test the
2x2 table exactly. A proxy that does not separate error is reported as not
separating error.

  * **cross-parser disagreement** -- needs a second parser at inference time.
  * **multi-run stability** -- needs the same input run twice. The aggregate
    metrics of two independent runs are indistinguishable, which is why this was
    first written off; but identical *scores* are not identical *outputs*. 180
    of 198 pages came back byte-identical and the 18 that did not are where the
    errors are. Greedy decoding does not make a model certain, it only removes
    deliberate sampling: where the model is genuinely undecided, ordinary
    numerical nondeterminism is enough to flip the answer.
  * **structural validity** -- markdown the model emitted that does not parse as
    a consistent document: ragged table rows, unclosed fences, empty headings.
    Needs nothing but the output.
  * **evidence consistency** -- whether the numbers, currency amounts and units
    the output states are internally coherent with the rest of the output. Needs
    nothing but the output.

The last two would be the cheapest -- no second parser, no second run -- and both
instruments written here were wrong. The structural check looks for ragged
markdown pipe tables; this model emits HTML tables, so it examined 0 tables
across 200 pages while the official evaluator scored 60. The consistency check
compares the output with a whitespace-normalised copy of itself, a transform that
cannot move a critical token. Both return a constant, and a constant from a
broken instrument is not a negative result. They are reported as untested.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.critical_tokens import verify_critical_tokens  # noqa: E402

ERROR_THRESHOLDS = (0.05, 0.10)
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
HEADING = re.compile(r"^\s*#{1,6}\s*(.*)$")
FENCE = re.compile(r"^\s*```")


def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
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


def structural_validity(markdown: str) -> float:
    """1.0 is a clean document; every defect found subtracts from it.

    Counted, not judged: rows in one table with differing column counts, an odd
    number of code fences, and headings with no text. All three are things a
    document cannot legitimately contain, so they need no threshold to call.
    """
    lines = markdown.splitlines()
    defects = 0
    considered = 0

    if len([line for line in lines if FENCE.match(line)]) % 2 == 1:
        defects += 1
    considered += 1

    block: list[int] = []
    for line in [*lines, ""]:
        if TABLE_ROW.match(line):
            block.append(line.count("|"))
            continue
        if len(block) >= 2:
            considered += 1
            if len(set(block)) > 1:
                defects += 1
        block = []

    for line in lines:
        match = HEADING.match(line)
        if match:
            considered += 1
            if not match.group(1).strip():
                defects += 1

    return 1.0 - (defects / considered if considered else 0.0)


def evidence_consistency(markdown: str) -> float:
    """Whether the output's own critical tokens survive its own normalisation.

    The output is compared with a whitespace- and case-normalised copy of itself.
    A document whose numbers are stable under that transform is internally
    coherent; one whose are not is emitting tokens that depend on formatting
    accidents, which is what a hallucinated table cell looks like.
    """
    normalised = re.sub(r"[ \t]+", " ", markdown)
    report = verify_critical_tokens(markdown, normalised)
    return 1.0 / (1.0 + len(report.mismatches))


def separation(
    pages: list[dict[str, Any]], proxy: str, threshold: float
) -> dict[str, Any]:
    values = [page[proxy] for page in pages]
    median = statistics.median(values)
    high = [p for p in pages if p[proxy] >= median]
    low = [p for p in pages if p[proxy] < median]
    if not high or not low:
        return {"usable": False, "why": f"{proxy} is constant across the corpus"}
    high_bad = sum(1 for p in high if p["error"][str(threshold)])
    low_bad = sum(1 for p in low if p["error"][str(threshold)])
    return {
        "usable": True,
        "median_split": median,
        "error_rate_high_proxy": high_bad / len(high),
        "error_rate_low_proxy": low_bad / len(low),
        "concentration_ratio": (
            (low_bad / len(low)) / (high_bad / len(high)) if high_bad else None
        ),
        "fisher_exact_p": fisher_exact_two_sided(
            high_bad, len(high) - high_bad, low_bad, len(low) - low_bad
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-a-predictions", type=Path, required=True)
    parser.add_argument("--run-a-artifacts", type=Path, required=True)
    parser.add_argument("--run-b-predictions", type=Path, required=True)
    parser.add_argument("--second-parser-predictions", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    edit_a = json.loads(
        (args.run_a_artifacts.resolve() / "text_block_per_page_edit.json").read_text(
            encoding="utf-8"
        )
    )
    # Run B's own scores are not read: correctness is always run A's, because
    # run A is the output the gate would have accepted. Run B is here only to
    # establish whether run A was stable.
    samples = json.loads(args.ground_truth.resolve().read_text(encoding="utf-8"))

    pages: list[dict[str, Any]] = []
    identical_runs = 0
    for sample in samples:
        image = str(sample["page_info"]["image_path"])
        stem = Path(image).stem
        if image not in edit_a:
            continue
        first = (args.run_a_predictions.resolve() / f"{stem}.md").read_text(
            encoding="utf-8"
        )
        second = (args.run_b_predictions.resolve() / f"{stem}.md").read_text(
            encoding="utf-8"
        )
        other = (args.second_parser_predictions.resolve() / f"{stem}.md").read_text(
            encoding="utf-8"
        )
        if first == second:
            identical_runs += 1
        page = {
            "image_path": image,
            "structural_validity": structural_validity(first),
            "evidence_consistency": evidence_consistency(first),
            "cross_parser_agreement": 1.0
            / (1.0 + len(verify_critical_tokens(first, other).mismatches)),
            "multi_run_stability": 1.0 if first == second else 0.0,
            "error": {
                str(t): float(edit_a[image]) > t for t in ERROR_THRESHOLDS
            },
        }
        pages.append(page)

    proxies = (
        "cross_parser_agreement",
        "structural_validity",
        "evidence_consistency",
        "multi_run_stability",
    )
    results: dict[str, Any] = {}
    for threshold in ERROR_THRESHOLDS:
        results[str(threshold)] = {
            proxy: separation(pages, proxy, threshold) for proxy in proxies
        }

    receipt = {
        "schema": "tavonel.a9-confidence-proxy-arm.v1",
        "experiment_id": "H1-A9-01",
        "naming_rule": (
            "None of these is a model self-confidence. The frozen runtime emits none. "
            "Any patent or manuscript text must name these as observable proxies and "
            "must not present them as a model's own confidence."
        ),
        "page_count": len(pages),
        "runs_with_byte_identical_output": identical_runs,
        "multi_run_stability_note": (
            f"{identical_runs} of {len(pages)} pages produced byte-identical output "
            "across two independent runs on different hosts at temperature 0.0. A "
            "proxy needs variation to carry information; this one has none here."
        ),
        "error_thresholds_text_edit_distance": list(ERROR_THRESHOLDS),
        "separation": results,
        "pages": sorted(pages, key=lambda p: p["image_path"]),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[proxy] byte-identical across runs: {identical_runs}/{len(pages)}", flush=True)
    for threshold in ERROR_THRESHOLDS:
        print(f"[proxy] error > {threshold}", flush=True)
        for proxy, data in results[str(threshold)].items():
            if not data["usable"]:
                print(f"[proxy]   {proxy}: UNUSABLE -- {data['why']}", flush=True)
                continue
            ratio = data["concentration_ratio"]
            shown = f"{ratio:.2f}x" if ratio else "n/a"
            print(
                f"[proxy]   {proxy}: {data['error_rate_high_proxy']:.3f} vs "
                f"{data['error_rate_low_proxy']:.3f} ({shown}) p={data['fisher_exact_p']:.4f}",
                flush=True,
            )
    print(f"[proxy] receipt: {args.output.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
