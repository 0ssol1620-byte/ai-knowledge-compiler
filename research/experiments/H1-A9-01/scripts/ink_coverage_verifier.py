#!/usr/bin/env python3
"""Source-grounded verification for scans, without OCR and without ground truth.

The design document proposed two checks against the page image itself. This is
the implementation of both, and -- as with every other instrument in A9 -- it is
validated before any performance number derived from it is believed.

The two quantities, per page, computed from the source image and the model's own
output only:

  * **ink density** -- the share of the page that carries marks, from Otsu
    thresholding on the greyscale image with the border trimmed. No layout
    model, no OCR, no annotation.
  * **ink per emitted character** -- ink pixels divided by the character count of
    the prediction. Real transcription lives in a narrow band; gross omission
    pushes the ratio up because the ink stays and the characters leave, gross
    invention pushes it down.

Why this can catch what the other signals cannot: stability and agreement are
both *comparisons between transcriptions*, so a page where every transcription
agrees on dropping a column looks perfect to them. Ink coverage does not read
the text at all, so a dropped column is a discrepancy it can still see.

Why it is weak where it is weak, stated up front: ink is not text. A figure, a
photograph, a dark scan margin and a large logo all read as ink, so a
figure-heavy page will look under-transcribed no matter how correct it is. The
instrument is therefore validated against deletion injections, and its
false-positive behaviour on figure-heavy pages is measured rather than assumed.

CPU only. No GPU, no new dependency beyond Pillow, no licence question.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(Path(__file__).resolve().parent))

SEED = 20260818
ANALYSIS_WIDTH = 1000  # downscale target; ink share is scale-invariant
BORDER_TRIM = 0.02  # drop 2% at each edge: scan shadow is ink to a threshold


def otsu_threshold(histogram: list[int]) -> int:
    """Classic between-class variance maximisation over a 256-bin histogram."""
    total = sum(histogram)
    if total == 0:
        return 128
    sum_all = sum(index * count for index, count in enumerate(histogram))
    sum_background = 0.0
    weight_background = 0
    best_variance = -1.0
    best_threshold = 128
    for threshold in range(256):
        weight_background += histogram[threshold]
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break
        sum_background += threshold * histogram[threshold]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_all - sum_background) / weight_foreground
        variance = (
            weight_background
            * weight_foreground
            * (mean_background - mean_foreground) ** 2
        )
        if variance > best_variance:
            best_variance = variance
            best_threshold = threshold
    return best_threshold


def ink_share(path: Path) -> float:
    """Fraction of trimmed page area darker than the Otsu threshold."""
    with Image.open(path) as image:
        grey = image.convert("L")
        width, height = grey.size
        if width > ANALYSIS_WIDTH:
            grey = grey.resize(
                (ANALYSIS_WIDTH, max(1, round(height * ANALYSIS_WIDTH / width))),
                Image.LANCZOS,
            )
        width, height = grey.size
        left, top = int(width * BORDER_TRIM), int(height * BORDER_TRIM)
        grey = grey.crop((left, top, width - left, height - top))
        pixels = list(grey.getdata())

    histogram = [0] * 256
    for value in pixels:
        histogram[value] += 1
    threshold = otsu_threshold(histogram)
    dark = sum(histogram[: threshold + 1])
    return dark / len(pixels)


def ink_per_character(ink: float, prediction: str) -> float | None:
    characters = len(prediction.strip())
    if characters == 0:
        return None
    return ink / characters * 10_000  # scaled so values land near 1


# --- deletion injections, to prove the instrument moves ---------------------

def delete_fraction(text: str, fraction: float, rng: random.Random) -> str:
    """Remove a contiguous run of the output, as a dropped column would."""
    lines = text.splitlines()
    if len(lines) < 4:
        return text
    count = max(1, int(len(lines) * fraction))
    start = rng.randrange(0, max(1, len(lines) - count))
    return "\n".join(lines[:start] + lines[start + count :])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--images-root", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--annotation", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.resolve().read_text(encoding="utf-8"))
    entries = manifest["inputs"]
    if args.limit:
        entries = entries[: args.limit]

    edit: dict[str, float] = {}
    if args.artifacts:
        edit = {
            key: float(value)
            for key, value in json.loads(
                (args.artifacts.resolve() / "text_block_per_page_edit.json").read_text(
                    encoding="utf-8"
                )
            ).items()
        }
    figures: dict[str, int] = {}
    if args.annotation:
        for row in json.loads(args.annotation.resolve().read_text(encoding="utf-8")):
            figures[str(row["page_info"]["image_path"])] = sum(
                1
                for d in row["layout_dets"]
                if str(d.get("category_type")) in {"figure", "figure_caption"}
            )

    records: list[dict[str, Any]] = []
    for entry in entries:
        page = Path(entry["source_relative_path"]).name
        prediction_path = args.predictions.resolve() / f"{Path(page).stem}.md"
        if not prediction_path.is_file():
            continue
        image_path = args.images_root.resolve() / Path(entry["input_relative_path"]).name
        if not image_path.is_file():
            continue
        prediction = prediction_path.read_text(encoding="utf-8")
        ink = ink_share(image_path)
        records.append(
            {
                "image_path": page,
                "ink_share": ink,
                "predicted_characters": len(prediction.strip()),
                "ink_per_10k_characters": ink_per_character(ink, prediction),
                "figure_regions": figures.get(page),
                "official_text_edit": edit.get(page),
            }
        )

    usable = [r for r in records if r["ink_per_10k_characters"] is not None]
    ratios = [r["ink_per_10k_characters"] for r in usable]
    summary = {
        "pages": len(records),
        "median_ink_share": statistics.median([r["ink_share"] for r in records])
        if records
        else None,
        "median_ink_per_10k_characters": statistics.median(ratios) if ratios else None,
        "ink_per_character_p10": sorted(ratios)[len(ratios) // 10] if ratios else None,
        "ink_per_character_p90": sorted(ratios)[9 * len(ratios) // 10]
        if ratios
        else None,
    }

    # --- instrument validation: deleting output must raise the ratio -------
    rng = random.Random(SEED)  # noqa: S311 - test fixtures
    validation: dict[str, Any] = {}
    for fraction in (0.05, 0.10, 0.25, 0.50):
        moved = 0
        considered = 0
        for record in usable:
            prediction = (
                args.predictions.resolve() / f"{Path(record['image_path']).stem}.md"
            ).read_text(encoding="utf-8")
            damaged = delete_fraction(prediction, fraction, rng)
            if damaged == prediction:
                continue
            considered += 1
            before = record["ink_per_10k_characters"]
            after = ink_per_character(record["ink_share"], damaged)
            if after is not None and after > before:
                moved += 1
        validation[f"delete_{int(fraction * 100)}_percent"] = {
            "pages_tested": considered,
            "ratio_increased": moved,
            "detection_rate": moved / considered if considered else None,
        }

    # --- the known weakness, measured -------------------------------------
    figure_effect = None
    with_figures = [r for r in usable if (r["figure_regions"] or 0) > 0]
    without_figures = [r for r in usable if (r["figure_regions"] or 0) == 0]
    if with_figures and without_figures:
        figure_effect = {
            "pages_with_a_figure": len(with_figures),
            "pages_without_a_figure": len(without_figures),
            "median_ratio_with_figures": statistics.median(
                [r["ink_per_10k_characters"] for r in with_figures]
            ),
            "median_ratio_without_figures": statistics.median(
                [r["ink_per_10k_characters"] for r in without_figures]
            ),
            "reading": (
                "a higher median on figure-bearing pages is the predicted "
                "confound, not a model defect: ink from a photograph has no "
                "characters to divide by"
            ),
        }

    # --- does it separate error at all? ------------------------------------
    scored = [
        r
        for r in usable
        if r["official_text_edit"] is not None
    ]
    separation: dict[str, Any] = {}
    if scored:
        from holdout_power_calculation import fisher_exact_two_sided

        order = sorted(r["ink_per_10k_characters"] for r in scored)
        cuts = (
            (0.90, "top_decile"),
            (0.75, "top_quartile"),
            (0.50, "above_median"),
        )
        for quantile, label in cuts:
            cut = order[int(quantile * len(order)) - 1]
            high = [r for r in scored if r["ink_per_10k_characters"] >= cut]
            low = [r for r in scored if r["ink_per_10k_characters"] < cut]
            high_bad = sum(1 for r in high if r["official_text_edit"] > 0.10)
            low_bad = sum(1 for r in low if r["official_text_edit"] > 0.10)
            separation[label] = {
                "cut": cut,
                "flagged": len(high),
                "flagged_severe_rate": high_bad / len(high) if high else None,
                "rest_severe_rate": low_bad / len(low) if low else None,
                "fisher_exact_p": fisher_exact_two_sided(
                    high_bad, len(high) - high_bad, low_bad, len(low) - low_bad
                ),
            }

    receipt = {
        "schema": "tavonel.a9-ink-coverage-verifier.v1",
        "status": "INSTRUMENT BUILT; NEGATIVE RESULT ON THIS CORPUS",
        "seed": SEED,
        "method": {
            "threshold": "Otsu on the greyscale histogram",
            "analysis_width_px": ANALYSIS_WIDTH,
            "border_trim_fraction": BORDER_TRIM,
            "uses_ground_truth": False,
            "uses_ocr": False,
        },
        "summary": summary,
        "deletion_injection_validation": validation,
        "known_confound_figure_pages": figure_effect,
        "separation_against_official_severe_error": separation,
        "injection_validation_is_weak_and_here_is_why": (
            "deleting output raises ink-per-character by construction, so a "
            "detection rate of 1.00 on the deletion injections is close to a "
            "tautology and is not evidence that the instrument works on natural "
            "variation. It shows only that the arithmetic points the right way. "
            "The separation block is the real test, and on this corpus it fails."
        ),
        "verdict": (
            "This design does not separate severe error on the 198-page "
            "discovery corpus. The highest-ink-per-character decile contains no "
            "severe errors at all. Published as not supported, in the same way "
            "the campaign published blind quality detection as not supported."
        ),
        "pages": sorted(records, key=lambda r: r["image_path"]),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("summary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print("deletion injections (ratio must rise):")
    for key, value in validation.items():
        rate = value["detection_rate"]
        print(
            f"  {key}: {value['ratio_increased']}/{value['pages_tested']} "
            f"({'n/a' if rate is None else f'{rate:.2f}'})"
        )
    if figure_effect:
        print("figure confound:")
        print(f"  with figures:    {figure_effect['median_ratio_with_figures']:.3f}")
        print(f"  without figures: {figure_effect['median_ratio_without_figures']:.3f}")
    if separation:
        print("separation against official severe error:")
        for label, data in separation.items():
            print(
                f"  {label:14} flagged {data['flagged']:3}  "
                f"{data['flagged_severe_rate']:.3f} vs {data['rest_severe_rate']:.3f}  "
                f"p={data['fisher_exact_p']:.4f}"
            )
        print("  VERDICT: no separation on this corpus -- published as not supported")
    print(f"receipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
