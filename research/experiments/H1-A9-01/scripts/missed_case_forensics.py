#!/usr/bin/env python3
"""The severe errors no gate caught, examined one at a time.

Six of the twelve severe errors are invisible to both the stability gate and the
agreement gate. Those six are the most informative pages in the corpus: they are
what a deployed selective-acceptance system would accept and be wrong about, so
whatever they have in common is the specification for a third signal -- or the
evidence that no cheap third signal exists.

Twelve severe errors is a small number and six is smaller. Nothing here is a
statistical claim. It is a census of six pages, reported as a census, and the
features are counted rather than judged so that the same census can be repeated
on a holdout without a person in the loop.
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
from repaired_output_instruments import evidence_defects  # noqa: E402

SEVERE = 0.10
CJK = re.compile(r"[一-鿿぀-ヿ]")


def ground_truth_text(sample: dict[str, Any]) -> str:
    return "\n\n".join(
        str(d.get("text") or d.get("html") or d.get("latex") or "")
        for d in sample["layout_dets"]
        if d.get("category_type") != "abandon"
    )


def profile(sample: dict[str, Any], prediction: str, edit: float) -> dict[str, Any]:
    info = sample["page_info"]
    attributes = info.get("page_attribute", {}) or {}
    categories: dict[str, int] = {}
    for det in sample["layout_dets"]:
        key = str(det.get("category_type"))
        categories[key] = categories.get(key, 0) + 1

    reference = ground_truth_text(sample)
    report = verify_critical_tokens(reference, prediction)
    structural = page_structural_flag(prediction)
    defects = evidence_defects(prediction)

    special = attributes.get("special_issue") or []
    special = [s for s in special if s and s != "None"]

    return {
        "image_path": str(info["image_path"]),
        "official_text_edit_distance": edit,
        "document_type": attributes.get("data_source"),
        "language": attributes.get("language"),
        "layout": attributes.get("layout"),
        "scan_quality_flags": special,
        "is_fuzzy_scan": "fuzzy_scan" in special,
        "pixel_width": info.get("width"),
        "pixel_height": info.get("height"),
        "region_count": len(sample["layout_dets"]),
        "categories": categories,
        "has_table": categories.get("table", 0) > 0,
        "has_formula": categories.get("equation_isolated", 0) > 0,
        "is_text_dominated": categories.get("text_block", 0)
        >= 0.5 * max(1, len(sample["layout_dets"])),
        "critical_token_mismatches": len(report.mismatches),
        "loses_a_critical_token": bool(report.mismatches),
        "structurally_defective": structural["structurally_defective"],
        "tables_emitted": structural["tables"],
        "evidence_defects": sum(defects.values()),
        "predicted_characters": len(prediction),
        "ground_truth_characters": len(reference),
        "length_ratio_prediction_over_truth": (
            len(prediction) / len(reference) if reference else None
        ),
        "cjk_share_of_ground_truth": (
            len(CJK.findall(reference)) / len(reference) if reference else 0.0
        ),
    }


def summarise(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = record[key]
        if isinstance(value, list):
            for item in value:
                counts[str(item)] = counts.get(str(item), 0) + 1
            continue
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--marginal-receipt", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    marginal = json.loads(args.marginal_receipt.resolve().read_text(encoding="utf-8"))
    missed = set(marginal["signal_marginal_gains"]["missed_by_stability_and_agreement"])
    edit = json.loads(
        (args.artifacts.resolve() / "text_block_per_page_edit.json").read_text(
            encoding="utf-8"
        )
    )
    samples = json.loads(args.ground_truth.resolve().read_text(encoding="utf-8"))

    missed_records: list[dict[str, Any]] = []
    caught_records: list[dict[str, Any]] = []
    clean_records: list[dict[str, Any]] = []
    for sample in samples:
        image = str(sample["page_info"]["image_path"])
        if image not in edit:
            continue
        text = (args.predictions.resolve() / f"{Path(image).stem}.md").read_text("utf-8")
        record = profile(sample, text, float(edit[image]))
        if float(edit[image]) > SEVERE:
            (missed_records if image in missed else caught_records).append(record)
        else:
            clean_records.append(record)

    def rate(records: list[dict[str, Any]], key: str) -> float | None:
        return (
            sum(1 for r in records if r[key]) / len(records) if records else None
        )

    def mean(records: list[dict[str, Any]], key: str) -> float | None:
        values = [r[key] for r in records if r[key] is not None]
        return sum(values) / len(values) if values else None

    groups = {
        "missed_by_both_gates": missed_records,
        "caught_by_a_gate": caught_records,
        "not_a_severe_error": clean_records,
    }
    comparison = {
        name: {
            "pages": len(records),
            "share_with_a_table": rate(records, "has_table"),
            "share_with_a_formula": rate(records, "has_formula"),
            "share_text_dominated": rate(records, "is_text_dominated"),
            "share_fuzzy_scan": rate(records, "is_fuzzy_scan"),
            "share_losing_a_critical_token": rate(records, "loses_a_critical_token"),
            "share_structurally_defective": rate(records, "structurally_defective"),
            "mean_critical_token_mismatches": mean(records, "critical_token_mismatches"),
            "mean_length_ratio": mean(records, "length_ratio_prediction_over_truth"),
            "mean_edit_distance": mean(records, "official_text_edit_distance"),
            "document_types": summarise(records, "document_type"),
        }
        for name, records in groups.items()
    }

    receipt = {
        "schema": "tavonel.a9-missed-case-forensics.v1",
        "status": "EXPLORATORY -- a census of six pages, not a statistical claim",
        "severe_error_definition": "official text-block edit distance > 0.10",
        "missed_case_count": len(missed_records),
        "caught_case_count": len(caught_records),
        "group_comparison": comparison,
        "missed_cases": sorted(
            missed_records, key=lambda r: -r["official_text_edit_distance"]
        ),
        "caught_cases": sorted(
            caught_records, key=lambda r: -r["official_text_edit_distance"]
        ),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"{'feature':38}{'missed':>10}{'caught':>10}{'clean':>10}")
    keys = [
        "pages",
        "share_with_a_table",
        "share_with_a_formula",
        "share_text_dominated",
        "share_fuzzy_scan",
        "share_losing_a_critical_token",
        "share_structurally_defective",
        "mean_critical_token_mismatches",
        "mean_length_ratio",
        "mean_edit_distance",
    ]
    for key in keys:
        row = [comparison[g][key] for g in groups]

        def show(value: float | int | None) -> str:
            if value is None:
                return "n/a"
            return f"{value:.3f}" if isinstance(value, float) else str(value)

        print(f"{key:38}{show(row[0]):>10}{show(row[1]):>10}{show(row[2]):>10}")

    print("\nthe six pages no gate caught:")
    for record in receipt["missed_cases"]:
        print(
            f"  {record['image_path'][:56]:58} edit={record['official_text_edit_distance']:.3f} "
            f"{record['document_type']}/{record['language']}/{record['layout']} "
            f"tables={record['tables_emitted']} "
            f"crit={record['critical_token_mismatches']} "
            f"len_ratio={record['length_ratio_prediction_over_truth']:.2f} "
            f"{'FUZZY' if record['is_fuzzy_scan'] else ''}"
        )
    print(f"\nreceipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
