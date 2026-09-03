#!/usr/bin/env python3
"""Measure critical-token corruption on the Stage-1 hard-200 real corpus.

`research/experiments/ASSURANCE-A-01` already runs `verify_critical_tokens` and
reports accuracy 1.0 -- on `synthetic-critical-token-v1`, a corpus whose
corruptions this repository injected itself. Weakness R3 exists because that
number says nothing about a hard real corpus. This measures the same verifier
against 200 real OmniDocBench pages and the model's real output.

What this measures, and what it deliberately does not:

  * It measures **how often a critical token in the ground truth fails to survive
    into the model's output** -- a number, date, currency amount, sign, unit or
    identifier. That is a measurement, not a label, and needs no human.

  * It cross-tabulates those pages against the official per-page text edit
    distance. A page with a low edit distance *looks* clean; if its critical
    tokens moved, the output is wrong in the way that matters while presenting
    as a success. That cross-tab is the whole point.

  * It does **not** report detector precision or recall. Those need a label of
    what is genuinely corrupt, arrived at independently of the detector, and on
    a real corpus that label is a human judgement. Deriving it from the same
    verifier would make precision 1.0 by construction, which is exactly how the
    synthetic pilot got its 1.0. `AssuranceMetrics` is deliberately not emitted.

  * It reports the cross-tab **at every threshold**, not one. No threshold in
    this repository is calibrated (`CalibrationTable.calibrated is False`), so
    picking one and calling its count "the silent corruption rate" would present
    an uncalibrated choice as a measured result.

Ground-truth text is assembled from every content-bearing category on the page,
including table HTML, isolated equations, headers and page numbers, because the
model transcribes the whole page. Assembling it from only the categories the
official text metric scores produced a spurious 178-of-200 "mutated" result on
the first attempt: the surplus tokens were real page content missing from the
reconstruction, not corruption in the output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.critical_tokens import verify_critical_tokens  # noqa: E402

# Every category on the page that carries content the model is expected to
# transcribe, with the field that holds it. Restricting this to the categories
# the official `text_block` metric scores was the first attempt and it was wrong:
# the model transcribes the whole page, so a header date or a table figure showed
# up as `output_count > source_count` and the run reported 178 of 200 pages
# "mutated" when the truth was that the ground-truth text had holes in it.
# Measured on newspaper_TheBostonGlobe-2025-1-8...page_033: the six reported
# number mismatches were 2025, 110 and 264 -- all real page content, none of it
# in the two-category reconstruction.
CONTENT_FIELDS = (
    ("text_block", "text"),
    ("title", "text"),
    ("header", "text"),
    ("footer", "text"),
    ("page_number", "text"),
    ("page_footnote", "text"),
    ("figure_caption", "text"),
    ("figure_footnote", "text"),
    ("figure", "text"),
    ("table_caption", "text"),
    ("table_footnote", "text"),
    ("table", "html"),
    ("equation_isolated", "latex"),
    ("list_group", "text"),
)

# `abandon`, `text_mask`, `unknown_mask` and `table_mask` are the categories
# OmniDocBench marks as not-to-be-read. They are excluded, and a model that reads
# them anyway will show up here as an unexplained surplus rather than be hidden.
EXCLUDED_CATEGORIES = ("abandon", "text_mask", "unknown_mask", "table_mask")

# Reported as a curve, never as a single answer. See the module docstring.
LOOKS_CLEAN_THRESHOLDS = (0.01, 0.02, 0.05, 0.10, 0.20)

NUMERIC_TOKEN = re.compile(r"[\d][\d,.]*")


def normalised(token: str) -> str:
    """Digits only, so `1,000` and `1000` are the same amount."""
    return re.sub(r"[,\s]", "", str(token)).lstrip("0") or "0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def ground_truth_text(sample: dict[str, Any]) -> str:
    """Reassemble everything on the page the model is expected to have read."""
    fields = dict(CONTENT_FIELDS)
    blocks: list[tuple[int, str]] = []
    for item in sample.get("layout_dets", []):
        category = item.get("category_type")
        if category in EXCLUDED_CATEGORIES or item.get("ignore"):
            continue
        field = fields.get(category)
        if field is None:
            continue
        content = str(item.get(field, "")).strip()
        if content:
            # Some annotations carry an explicit null order; those sort last
            # rather than crash, and order only affects concatenation, never
            # the multiset of critical tokens being compared.
            order = item.get("order")
            blocks.append((int(order) if isinstance(order, int | float) else 1 << 30, content))
    blocks.sort(key=lambda pair: pair[0])
    return "\n".join(content for _, content in blocks)


def load_official_text_edit(artifact_dir: Path) -> dict[str, float]:
    path = artifact_dir / "text_block_per_page_edit.json"
    if not path.is_file():
        raise FileNotFoundError(f"official per-page text edit artifact missing: {path}")
    return {
        str(page): float(value)
        for page, value in json.loads(path.read_text(encoding="utf-8")).items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--official-artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    ground_truth = args.ground_truth.resolve()
    samples = json.loads(ground_truth.read_text(encoding="utf-8"))
    official_edit = load_official_text_edit(args.official_artifacts.resolve())

    records: list[dict[str, Any]] = []
    kind_counter: Counter[str] = Counter()
    for sample in samples:
        image = str(sample["page_info"]["image_path"])
        prediction = args.predictions.resolve() / f"{Path(image).stem}.md"
        if not prediction.is_file():
            raise RuntimeError(
                f"no prediction for {image}. Scoring a missing page as a miss is how "
                "184 of 200 pages were silently zeroed on 2026-08-18."
            )
        source = ground_truth_text(sample)
        output = prediction.read_text(encoding="utf-8")
        report = verify_critical_tokens(source, output)
        kinds = sorted({str(mismatch.kind.value) for mismatch in report.mismatches})
        kind_counter.update(kinds)

        # Direction matters more than the mismatch count. A token in the ground
        # truth that did not survive into the output is the failure this project
        # cares about. A token the output has and the ground truth does not is
        # usually text inside a figure: OmniDocBench annotates 343 figure regions
        # and gives only 10 of them any text, so a model that reads a chart axis
        # produces numbers with no counterpart. Counting those as corruption
        # would blame the model for reading more of the page than the annotation
        # describes.
        output_tokens = {normalised(t) for t in NUMERIC_TOKEN.findall(output)}
        lost = [m for m in report.mismatches if m.output_count < m.source_count]
        surplus = [m for m in report.mismatches if m.output_count > m.source_count]
        # `1,000` against `1000` is a formatting difference, not a lost amount,
        # and it otherwise registers as a loss and a surplus at the same time.
        lost_formatting = [m for m in lost if normalised(m.token) in output_tokens]
        records.append(
            {
                "image_path": image,
                "ground_truth_characters": len(source),
                "output_characters": len(output),
                "official_text_edit_distance": official_edit.get(image),
                "critical_token_passed": report.passed,
                "mismatch_kinds": kinds,
                "mismatch_count": len(report.mismatches),
                "lost_token_count": len(lost),
                "lost_explained_by_formatting": len(lost_formatting),
                "lost_unexplained": len(lost) - len(lost_formatting),
                "surplus_token_count": len(surplus),
                "highest_risk": max(
                    (float(mismatch.risk) for mismatch in report.mismatches), default=0.0
                ),
            }
        )

    scored = [r for r in records if r["official_text_edit_distance"] is not None]
    mutated = [r for r in records if not r["critical_token_passed"]]
    curve = []
    for threshold in LOOKS_CLEAN_THRESHOLDS:
        looks_clean = [
            r for r in scored if float(r["official_text_edit_distance"]) <= threshold
        ]
        both = [r for r in looks_clean if r["lost_unexplained"] > 0]
        curve.append(
            {
                "text_edit_distance_at_or_below": threshold,
                "pages_that_look_clean": len(looks_clean),
                "of_those_losing_a_ground_truth_token": len(both),
            }
        )

    receipt = {
        "schema": "tavonel.stage1-hard200-critical-token-measurement.v1",
        "corpus_id": "omnidocbench-hard200-real",
        "verifier": "akc_cir.critical_tokens.verify_critical_tokens",
        "ground_truth_sha256": sha256_file(ground_truth),
        "ground_truth_categories": [f"{c}.{f}" for c, f in CONTENT_FIELDS],
        "excluded_categories": list(EXCLUDED_CATEGORIES),
        "predictions_root": str(args.predictions.resolve()),
        "page_count": len(records),
        "pages_missing_official_edit_distance": len(records) - len(scored),
        "pages_with_a_critical_token_mismatch": len(mutated),
        "pages_losing_a_ground_truth_token": sum(
            1 for r in records if r["lost_unexplained"] > 0
        ),
        "pages_with_surplus_only": sum(
            1 for r in records if r["surplus_token_count"] and not r["lost_token_count"]
        ),
        "lost_token_mismatches": sum(r["lost_token_count"] for r in records),
        "lost_explained_by_formatting": sum(
            r["lost_explained_by_formatting"] for r in records
        ),
        "lost_unexplained": sum(r["lost_unexplained"] for r in records),
        "output_shorter_than_85_percent_of_ground_truth": sum(
            1
            for r in records
            if r["output_characters"] < 0.85 * max(r["ground_truth_characters"], 1)
        ),
        "mismatch_kind_page_counts": dict(sorted(kind_counter.items())),
        "looks_clean_but_mutated": curve,
        "not_measured": [
            "detector precision and recall -- needs an independent label of what is "
            "genuinely corrupt, which on a real corpus is a human judgement",
            "abstention -- this run produced output for all 200 pages "
            "(stage1-receipt.json: completed 200, failed 0), so there is nothing to "
            "measure until a run declines a page",
        ],
        "records": sorted(records, key=lambda r: r["image_path"]),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"[critical-token] {sum(1 for r in records if r['lost_unexplained'] > 0)}"
        f"/{len(records)} pages lose at least one ground-truth critical token "
        f"(surplus-only pages excluded)",
        flush=True,
    )
    for row in curve:
        print(
            f"[critical-token] edit<= {row['text_edit_distance_at_or_below']:.2f}: "
            f"{row['of_those_losing_a_ground_truth_token']}"
            f"/{row['pages_that_look_clean']} look clean but mutated",
            flush=True,
        )
    print(f"[critical-token] receipt: {args.output.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
