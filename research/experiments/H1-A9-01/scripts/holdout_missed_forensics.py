#!/usr/bin/env python3
"""Secondary, exploratory: what did the gate miss on the holdout?

Strictly after the primary test. Nothing here can change the primary result and
nothing here is a confirmatory claim -- it is the discovery-set census repeated
on data the census never saw, which is the only way to find out whether the
pattern it found was real or was six pages of coincidence.

The discovery census produced four hypotheses about pages the gate misses:

  1. they carry no tables, so structural signals cannot reach them;
  2. their prediction-to-truth length ratio is close to 1, so nothing is grossly
     omitted or invented;
  3. they lose far fewer critical tokens than the errors the gate does catch;
  4. they transcribe ground-truth-excluded regions -- running headers, page
     numbers, figure captions, logo text -- at a higher rate than the corpus.

Each is stated as a prediction with a direction, and each is checked against the
holdout the same way. A hypothesis that fails is reported as failed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from akc_cir.critical_tokens import verify_critical_tokens  # noqa: E402
from evaluator_aligned_instruments import page_structural_flag  # noqa: E402

EXCLUDED_CATEGORIES = frozenset(
    {
        "abandon",
        "header",
        "footer",
        "page_number",
        "page_footnote",
        "figure_caption",
        "figure_footnote",
    }
)
MINIMUM_EXCLUDED_LENGTH = 6


def squashed(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def ground_truth_text(sample: dict[str, Any]) -> str:
    return "\n\n".join(
        str(d.get("text") or d.get("html") or d.get("latex") or "")
        for d in sample["layout_dets"]
        if d.get("category_type") != "abandon"
    )


def profile(sample: dict[str, Any], prediction: str) -> dict[str, Any]:
    info = sample["page_info"]
    attributes = info.get("page_attribute", {}) or {}
    categories: dict[str, int] = {}
    for det in sample["layout_dets"]:
        categories[str(det.get("category_type"))] = (
            categories.get(str(det.get("category_type")), 0) + 1
        )
    reference = ground_truth_text(sample)
    structural = page_structural_flag(prediction)
    squashed_prediction = squashed(prediction)
    excluded = [
        str(det.get("text") or "")
        for det in sample["layout_dets"]
        if det.get("category_type") in EXCLUDED_CATEGORIES and det.get("text")
    ]
    excluded = [text for text in excluded if len(squashed(text)) >= MINIMUM_EXCLUDED_LENGTH]
    emitted = sum(1 for text in excluded if squashed(text) in squashed_prediction)
    special = [
        s for s in (attributes.get("special_issue") or []) if s and s != "None"
    ]
    return {
        "image_path": str(info["image_path"]),
        "document_type": attributes.get("data_source"),
        "language": attributes.get("language"),
        "layout": attributes.get("layout"),
        "scan_quality_flags": special,
        "is_fuzzy_scan": "fuzzy_scan" in special,
        "has_table": categories.get("table", 0) > 0,
        "has_formula": categories.get("equation_isolated", 0) > 0,
        "critical_token_mismatches": len(
            verify_critical_tokens(reference, prediction).mismatches
        ),
        "structurally_defective": structural["structurally_defective"],
        "length_ratio_prediction_over_truth": (
            len(prediction) / len(reference) if reference else None
        ),
        "excluded_regions": len(excluded),
        "excluded_regions_emitted": emitted,
        "excluded_region_emission_rate": (
            emitted / len(excluded) if excluded else None
        ),
    }


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    def share(key: str) -> float | None:
        return sum(1 for r in records if r[key]) / len(records) if records else None

    def mean(key: str) -> float | None:
        values = [r[key] for r in records if r[key] is not None]
        return sum(values) / len(values) if values else None

    excluded_total = sum(r["excluded_regions"] for r in records)
    emitted_total = sum(r["excluded_regions_emitted"] for r in records)
    return {
        "pages": len(records),
        "share_with_a_table": share("has_table"),
        "share_with_a_formula": share("has_formula"),
        "share_fuzzy_scan": share("is_fuzzy_scan"),
        "share_structurally_defective": share("structurally_defective"),
        "mean_critical_token_mismatches": mean("critical_token_mismatches"),
        "mean_length_ratio": mean("length_ratio_prediction_over_truth"),
        "excluded_regions": excluded_total,
        "excluded_regions_emitted": emitted_total,
        "excluded_region_emission_rate": (
            emitted_total / excluded_total if excluded_total else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmatory-result", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--annotation", type=Path, required=True)
    parser.add_argument("--discovery-forensics", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = json.loads(args.confirmatory_result.resolve().read_text(encoding="utf-8"))
    annotation = json.loads(args.annotation.resolve().read_text(encoding="utf-8"))
    by_page = {str(row["page_info"]["image_path"]): row for row in annotation}

    groups: dict[str, list[dict[str, Any]]] = {
        "missed_by_the_gate": [],
        "caught_by_the_gate": [],
        "not_a_severe_error": [],
    }
    for page in result["pages"]:
        sample = by_page.get(page["image_path"])
        if sample is None:
            continue
        text = (
            args.predictions.resolve() / f"{Path(page['image_path']).stem}.md"
        ).read_text(encoding="utf-8")
        record = profile(sample, text)
        record["accepted"] = page["accepted"]
        record["official_text_edit"] = page["official_text_edit"]
        if not page["severe"]:
            groups["not_a_severe_error"].append(record)
        elif page["accepted"]:
            groups["missed_by_the_gate"].append(record)
        else:
            groups["caught_by_the_gate"].append(record)

    comparison = {name: summarise(records) for name, records in groups.items()}

    missed = comparison["missed_by_the_gate"]
    caught = comparison["caught_by_the_gate"]
    clean = comparison["not_a_severe_error"]

    def held(value: bool | None) -> str:
        if value is None:
            return "UNTESTABLE"
        return "REPRODUCED" if value else "NOT_REPRODUCED"

    hypotheses = {
        "missed_cases_carry_fewer_tables": {
            "prediction": "share_with_a_table lower for missed than for caught",
            "missed": missed["share_with_a_table"],
            "caught": caught["share_with_a_table"],
            "verdict": held(
                None
                if missed["pages"] == 0 or caught["pages"] == 0
                else missed["share_with_a_table"] < caught["share_with_a_table"]
            ),
        },
        "missed_cases_have_length_ratio_near_one": {
            "prediction": "mean_length_ratio closer to 1.0 for missed than for caught",
            "missed": missed["mean_length_ratio"],
            "caught": caught["mean_length_ratio"],
            "verdict": held(
                None
                if missed["pages"] == 0 or caught["pages"] == 0
                else abs((missed["mean_length_ratio"] or 0) - 1)
                < abs((caught["mean_length_ratio"] or 0) - 1)
            ),
        },
        "missed_cases_lose_fewer_critical_tokens": {
            "prediction": "mean_critical_token_mismatches lower for missed",
            "missed": missed["mean_critical_token_mismatches"],
            "caught": caught["mean_critical_token_mismatches"],
            "verdict": held(
                None
                if missed["pages"] == 0 or caught["pages"] == 0
                else (missed["mean_critical_token_mismatches"] or 0)
                < (caught["mean_critical_token_mismatches"] or 0)
            ),
        },
        "missed_cases_transcribe_excluded_regions_more": {
            "prediction": (
                "excluded_region_emission_rate higher for missed than for the "
                "non-severe corpus"
            ),
            "missed": missed["excluded_region_emission_rate"],
            "corpus": clean["excluded_region_emission_rate"],
            "verdict": held(
                None
                if missed["excluded_regions"] == 0 or clean["excluded_regions"] == 0
                else (missed["excluded_region_emission_rate"] or 0)
                > (clean["excluded_region_emission_rate"] or 0)
            ),
        },
    }

    receipt = {
        "schema": "tavonel.a9-holdout-forensics.v1",
        "status": "SECONDARY, EXPLORATORY -- run after the primary test",
        "not_a_confirmatory_claim": (
            "these are the discovery census's hypotheses checked on the holdout; "
            "they were not pre-registered as endpoints and no p-value is reported"
        ),
        "group_comparison": comparison,
        "discovery_hypotheses_rechecked": hypotheses,
        "missed_cases": sorted(
            groups["missed_by_the_gate"],
            key=lambda r: -r["official_text_edit"],
        ),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"{'feature':40}{'missed':>10}{'caught':>10}{'clean':>10}")
    for key in comparison["missed_by_the_gate"]:
        row = [comparison[g].get(key) for g in groups]

        def show(value: Any) -> str:
            if value is None:
                return "n/a"
            return f"{value:.3f}" if isinstance(value, float) else str(value)

        print(f"{key:40}{show(row[0]):>10}{show(row[1]):>10}{show(row[2]):>10}")
    print("\ndiscovery hypotheses rechecked on the holdout:")
    for name, data in hypotheses.items():
        print(f"  {name}: {data['verdict']}")
    print(f"\nreceipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
