#!/usr/bin/env python3
"""Which pages the official evaluator gives a text score to, and why it matters.

The confirmatory test drops any page with no official text-block edit distance,
because the primary endpoint is defined on that number and a page without one
has no endpoint. On the frozen 800 that is 51 pages.

A dropped page is a threat before it is a detail. If pages disappeared from the
denominator for a reason connected to the model's output -- an empty prediction,
a matcher timeout, a page so badly transcribed that nothing aligned -- then the
exclusion would remove exactly the pages most likely to be severe errors, and
the measured error rate would be biased downward by construction. That would not
show up anywhere in the test statistic.

So the criterion is not assumed, it is derived and checked: a page is scored if
and only if its **ground truth** contains at least one body-text region --
`text_block`, `title`, `reference` or `code_txt`. Captions, footnotes, headers,
footers and page numbers do not qualify on their own, which is why 51 table-only
and figure-only pages carry no text score.

Measured on the 800-page holdout: that rule reproduces the evaluator's decision
on **800 of 800 pages, with no exceptions in either direction**. Every input to
it comes from the annotation. The predictions are not read, so the exclusion
cannot correlate with prediction quality, and the pages that leave the
denominator leave it for a reason fixed before the model ran.

What this does not claim: that the excluded pages are unimportant. A table-only
page can be transcribed catastrophically. It claims only that the official text
metric does not measure them, and that their removal is not selective.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Derived by exhaustive search over the 800-page holdout against the evaluator's
# own per-page output: this is the smallest category set that reproduces its
# decision exactly. The broader 16-category group the evaluator uses to bucket
# *matched* elements is not the right set -- 48 pages carry only captions,
# footnotes or page numbers from that group and are still unscored.
BODY_TEXT_CATEGORIES = frozenset({"text_block", "title", "reference", "code_txt"})


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def has_body_text(record: dict[str, Any]) -> bool:
    """Does this ground-truth page carry any region the text metric scores?"""
    return any(
        str(detection.get("category_type")) in BODY_TEXT_CATEGORIES
        for detection in record.get("layout_dets", [])
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    ground_truth = json.loads(
        args.ground_truth.resolve().read_text(encoding="utf-8")
    )
    edit = json.loads(
        (args.artifacts.resolve() / "text_block_per_page_edit.json").read_text(
            encoding="utf-8"
        )
    )

    predicted_scored = 0
    predicted_unscored = 0
    unscored_despite_body_text: list[str] = []
    scored_without_body_text: list[str] = []
    excluded_categories: Counter[str] = Counter()
    excluded_sources: Counter[str] = Counter()

    for record in ground_truth:
        image = record["page_info"]["image_path"]
        eligible = has_body_text(record)
        scored = image in edit
        if eligible:
            predicted_scored += 1
            if not scored:
                unscored_despite_body_text.append(image)
        else:
            predicted_unscored += 1
            if scored:
                scored_without_body_text.append(image)
            else:
                excluded_sources[
                    str(record["page_info"].get("page_attribute", {}).get("data_source"))
                ] += 1
                for detection in record["layout_dets"]:
                    excluded_categories[str(detection.get("category_type"))] += 1

    exact = not unscored_despite_body_text and not scored_without_body_text

    receipt = {
        "schema": "tavonel.a9-scored-page-criterion.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "body_text_categories": sorted(BODY_TEXT_CATEGORIES),
        "pages_in_ground_truth": len(ground_truth),
        "pages_scored_by_the_evaluator": len(
            [r for r in ground_truth if r["page_info"]["image_path"] in edit]
        ),
        "pages_predicted_scored": predicted_scored,
        "pages_predicted_unscored": predicted_unscored,
        "disagreements_unscored_despite_body_text": unscored_despite_body_text,
        "disagreements_scored_without_body_text": scored_without_body_text,
        "criterion_reproduces_the_evaluator_exactly": exact,
        "criterion_reads_predictions": False,
        "why_this_matters": (
            "the confirmatory endpoint is undefined on an unscored page, so those "
            "pages leave the denominator. If they left it for a reason correlated "
            "with output quality -- empty prediction, matcher timeout, nothing "
            "aligned -- the measured error rate would be biased downward and the "
            "test statistic would not show it. This criterion is computed from "
            "the annotation alone, so the exclusion is fixed before the model runs."
        ),
        "what_is_not_claimed": (
            "not that the excluded pages are safe. A table-only page can be "
            "transcribed catastrophically. Only that the official text metric "
            "does not measure them and their removal is not selective."
        ),
        "excluded_page_data_sources": excluded_sources.most_common(),
        "excluded_page_region_categories": excluded_categories.most_common(),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)

    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"ground truth pages         : {receipt['pages_in_ground_truth']}")
    print(f"evaluator scored           : {receipt['pages_scored_by_the_evaluator']}")
    print(f"criterion predicts scored  : {predicted_scored}")
    print(f"disagreements              : "
          f"{len(unscored_despite_body_text)} unscored-with-body-text, "
          f"{len(scored_without_body_text)} scored-without")
    print(f"exact                      : {exact}")
    if not exact:
        raise SystemExit(
            "the scored-page criterion does not reproduce the evaluator. The "
            "exclusion is then not explained by ground truth alone and must be "
            "investigated before the confirmatory denominator can be trusted."
        )
    print(f"receipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
