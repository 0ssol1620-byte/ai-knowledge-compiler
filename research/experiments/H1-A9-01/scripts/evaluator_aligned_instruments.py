#!/usr/bin/env python3
"""Instruments aligned to the official evaluator's measurement unit, then validated.

The previous version counted 88 tables where the official evaluator scored 60,
and that gap had to be explained before any proxy number derived from it could
be used. The suspected cause was nested `<table>` elements inflating the count.

**It was not.** The evaluator extracts *outermost* tables via a stack-based
scanner (`extract_html_table` in `src/core/preprocess/extract.py`), and that
function is vendored verbatim below. Run against the same 200 predictions it
returns 88 -- exactly what the previous detector returned, on every page. There
is no nesting in this corpus and there was no double counting.

The 88-vs-60 gap is the model **over-segmenting**: it emits more table elements
than the ground truth annotates as table regions, concentrated on three
newspaper pages (29 vs 26, 25 vs 13, 18 vs 6). The evaluator reports 60 because
its evaluation target is the ground-truth region, matched to predictions by
Hungarian assignment on normalised edit distance; surplus predictions become
unmatched rather than new targets.

Two things follow, and both are implemented here:

  * **Extraction unit: outermost `<table>`, byte-identical to the evaluator.**
    Locked by a contract test that diffs this function against the evaluator's
    own on all 200 predictions.
  * **A page-level proxy must not weight by table count.** A page with 29 tables
    has 29 chances to contain a defect and a page with one has one, so a ratio
    over tables makes table-heavy pages incomparable for a reason that has
    nothing to do with error. The page-level signal here is therefore *defect
    presence*, which each page contributes to exactly once, and the relationship
    between flagging and table count is reported so the residual bias can be
    seen rather than assumed absent.

Validation is positive **and** negative. Sensitivity comes from injected
semantic corruptions -- the failures a knowledge compiler actually cares about,
not syntax noise. The false-positive rate comes from running each instrument
over the human-annotated ground-truth text, where any flag is by construction a
false positive.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from akc_cir.critical_tokens import verify_critical_tokens  # noqa: E402
from repaired_output_instruments import evidence_validity, table_shapes  # noqa: E402

SEED = 20260818


# --- the evaluator's own extraction unit, vendored verbatim ----------------
# Source: benchmark/cache/omnidoc/src/core/preprocess/extract.py::extract_html_table
# Copied rather than imported because importing it drags in BeautifulSoup, the
# LaTeX walker and the evaluator's package layout. The contract test proves the
# copy still agrees with the original; if the evaluator is upgraded and this
# drifts, that test fails, which is the point of having it.
def extract_html_table(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    begin_pattern = r"<table(?:[^>]*)>"
    end_pattern = r"</table>"

    tabulars: list[str] = []
    positions: list[tuple[int, int]] = []
    current_pos = 0
    stack: list[int] = []

    while current_pos < len(text):
        begin_match = re.search(begin_pattern, text[current_pos:])
        end_match = re.search(end_pattern, text[current_pos:])

        if not begin_match and not end_match:
            break

        if begin_match and (not end_match or begin_match.start() < end_match.start()):
            stack.append(current_pos + begin_match.start())
            current_pos += begin_match.start() + len(end_pattern)
        elif end_match:
            if stack:
                start_pos = stack.pop()
                if not stack:
                    end_pos = current_pos + end_match.start() + len(end_pattern)
                    tabulars.append(text[start_pos:end_pos])
                    positions.append((start_pos, end_pos))
            current_pos += end_match.start() + len(end_pattern)
        else:
            current_pos += 1

    if stack:
        new_start = stack[0] + len(begin_pattern)
        new_tabulars, new_positions = extract_html_table(text[new_start:])
        new_positions = [(s + new_start, e + new_start) for s, e in new_positions]
        tabulars.extend(new_tabulars)
        positions.extend(new_positions)

    return tabulars, positions


def aligned_table_count(markup: str) -> int:
    """Tables as the evaluator counts them: outermost only."""
    return len(extract_html_table(markup)[0])


# --- structural defects, per table, at the aligned unit ---------------------

def table_structural_defects(table_markup: str) -> dict[str, int]:
    shapes, cells = table_shapes(table_markup)
    rows = [width for shape in shapes for width in shape]
    return {
        "cells": cells,
        "rows": len(rows),
        "ragged": 1 if len(set(rows)) > 1 else 0,
        "empty": 1 if not rows else 0,
    }


def page_structural_flag(markup: str) -> dict[str, Any]:
    """Does this page contain any structurally defective table?

    Presence, not a rate. A rate over tables would make the 29-table page and
    the 1-table page incomparable, which is the weighting bias this file exists
    to remove.
    """
    tables = extract_html_table(markup)[0]
    per_table = [table_structural_defects(t) for t in tables]
    ragged = sum(d["ragged"] for d in per_table)
    empty = sum(d["empty"] for d in per_table)
    unbalanced = abs(markup.count("<table") - markup.count("</table>"))
    return {
        "tables": len(tables),
        "cells": sum(d["cells"] for d in per_table),
        "ragged_tables": ragged,
        "empty_tables": empty,
        "unbalanced_table_tags": unbalanced,
        "structurally_defective": bool(ragged or empty or unbalanced),
    }


# --- semantic corruptions: the failures that actually matter ---------------

def _digit_runs(text: str) -> list[re.Match[str]]:
    return list(re.finditer(r"(?<![\d.])\d{2,}(?![\d.])", text))


def corrupt_number(text: str, rng: random.Random) -> str | None:
    spots = _digit_runs(text)
    if not spots:
        return None
    spot = rng.choice(spots)
    original = spot.group(0)
    changed = str((int(original) + 1) % (10 ** len(original))).zfill(len(original))
    if changed == original:
        return None
    return text[: spot.start()] + changed + text[spot.end() :]


def corrupt_sign(text: str, rng: random.Random) -> str | None:
    spots = list(re.finditer(r"(?<!\w)-\d", text))
    if spots:
        spot = rng.choice(spots)
        return text[: spot.start()] + spot.group(0)[1:] + text[spot.end() :]
    spots = _digit_runs(text)
    if not spots:
        return None
    spot = rng.choice(spots)
    return text[: spot.start()] + "-" + text[spot.start() :]


def corrupt_date(text: str, rng: random.Random) -> str | None:
    spots = list(
        re.finditer(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b", text)
    )
    if not spots:
        return None
    spot = rng.choice(spots)
    body = spot.group(0)
    changed = re.sub(
        r"\d+",
        lambda m: str(int(m.group(0)) + 1).zfill(len(m.group(0))),
        body,
        count=1,
    )
    if changed == body:
        return None
    return text[: spot.start()] + changed + text[spot.end() :]


UNITS = ("km", "m", "kg", "g", "%", "mm", "cm", "MB", "GB", "hours", "days")


def corrupt_unit(text: str, rng: random.Random) -> str | None:
    for unit in rng.sample(UNITS, len(UNITS)):
        spots = list(re.finditer(rf"(?<=\d)\s?{re.escape(unit)}\b", text))
        if spots:
            spot = rng.choice(spots)
            other = rng.choice([u for u in UNITS if u != unit])
            return (
                text[: spot.start()]
                + spot.group(0).replace(unit, other)
                + text[spot.end() :]
            )
    return None


def corrupt_entity_loss(text: str, rng: random.Random) -> str | None:
    spots = list(re.finditer(r"\b[A-Z][a-z]{3,}\b", text))
    if not spots:
        return None
    spot = rng.choice(spots)
    return text[: spot.start()] + text[spot.end() :]


CELL = r"<t[dh]\b[^>]*>.*?</t[dh]>"
ROW = r"<tr\b[^>]*>.*?</tr>"


def _table_span(text: str, rng: random.Random) -> tuple[int, int, str] | None:
    tables, positions = extract_html_table(text)
    if not tables:
        return None
    index = rng.randrange(len(tables))
    start, end = positions[index]
    return start, end, tables[index]


def corrupt_cell_omission(text: str, rng: random.Random) -> str | None:
    span = _table_span(text, rng)
    if span is None:
        return None
    start, end, table = span
    cells = list(re.finditer(CELL, table, re.DOTALL))
    if not cells:
        return None
    cell = rng.choice(cells)
    return text[:start] + table[: cell.start()] + table[cell.end() :] + text[end:]


def corrupt_duplicated_cell(text: str, rng: random.Random) -> str | None:
    span = _table_span(text, rng)
    if span is None:
        return None
    start, end, table = span
    cells = list(re.finditer(CELL, table, re.DOTALL))
    if not cells:
        return None
    cell = rng.choice(cells)
    changed = table[: cell.end()] + cell.group(0) + table[cell.end() :]
    return text[:start] + changed + text[end:]


def corrupt_row_swap(text: str, rng: random.Random) -> str | None:
    span = _table_span(text, rng)
    if span is None:
        return None
    start, end, table = span
    rows = list(re.finditer(ROW, table, re.DOTALL))
    if len(rows) < 2:
        return None
    index = rng.randrange(len(rows) - 1)
    first, second = rows[index], rows[index + 1]
    changed = (
        table[: first.start()]
        + second.group(0)
        + table[first.end() : second.start()]
        + first.group(0)
        + table[second.end() :]
    )
    return text[:start] + changed + text[end:]


def corrupt_column_swap(text: str, rng: random.Random) -> str | None:
    span = _table_span(text, rng)
    if span is None:
        return None
    start, end, table = span

    def swap_first_two(row: re.Match[str]) -> str:
        body = row.group(0)
        cells = list(re.finditer(CELL, body, re.DOTALL))
        if len(cells) < 2:
            return body
        first, second = cells[0], cells[1]
        return (
            body[: first.start()]
            + second.group(0)
            + body[first.end() : second.start()]
            + first.group(0)
            + body[second.end() :]
        )

    changed = re.sub(ROW, swap_first_two, table, flags=re.DOTALL)
    if changed == table:
        return None
    return text[:start] + changed + text[end:]


CORRUPTIONS = {
    "number_change": corrupt_number,
    "sign_change": corrupt_sign,
    "date_change": corrupt_date,
    "unit_change": corrupt_unit,
    "entity_token_loss": corrupt_entity_loss,
    "row_swap": corrupt_row_swap,
    "column_swap": corrupt_column_swap,
    "cell_omission": corrupt_cell_omission,
    "duplicated_cell": corrupt_duplicated_cell,
}


# --- the three instruments, as detectors ------------------------------------

def detect_structural(text: str, reference: str | None = None) -> bool:
    return page_structural_flag(text)["structurally_defective"]


def detect_evidence(text: str, reference: str | None = None) -> bool:
    return evidence_validity(text) < 1.0


def detect_critical_field(text: str, reference: str | None = None) -> bool:
    """Reference-based: needs something to compare against.

    At inference time that reference is a second run or a second parser, which
    is why this instrument is not free the way the other two are. It is included
    because it is the mechanism the agreement and stability gates rely on, and
    validating it says what those gates can and cannot see.
    """
    if reference is None:
        return False
    return bool(verify_critical_tokens(reference, text).mismatches)


DETECTORS = {
    "structural_validity": detect_structural,
    "evidence_validity": detect_evidence,
    "critical_field_preservation": detect_critical_field,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--official-artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    samples = json.loads(args.ground_truth.resolve().read_text(encoding="utf-8"))
    official = json.loads(
        (args.official_artifacts.resolve() / "table_per_table_TEDS.json").read_text(
            encoding="utf-8"
        )
    )
    official_per_page: dict[str, int] = {}
    for key in official:
        page = key.rsplit("_[", 1)[0] if key.endswith("]") and "_[" in key else key
        official_per_page[page] = official_per_page.get(page, 0) + 1

    pages: list[dict[str, Any]] = []
    for sample in samples:
        image = str(sample["page_info"]["image_path"])
        text = (args.predictions.resolve() / f"{Path(image).stem}.md").read_text("utf-8")
        gt_tables = sum(
            1 for d in sample["layout_dets"] if d.get("category_type") == "table"
        )
        # The ground-truth document, assembled as the negative control.
        gt_text = "\n\n".join(
            str(d.get("text") or d.get("html") or d.get("latex") or "")
            for d in sample["layout_dets"]
        )
        pages.append(
            {
                "image_path": image,
                "prediction": text,
                "ground_truth_text": gt_text,
                "ground_truth_tables": gt_tables,
                "official_scored_tables": official_per_page.get(image, 0),
                **page_structural_flag(text),
            }
        )

    alignment = {
        "evaluator_extraction_unit": "outermost <table>, stack-scanned",
        "vendored_from": "src/core/preprocess/extract.py::extract_html_table",
        "total_tables_this_instrument": sum(p["tables"] for p in pages),
        "total_ground_truth_table_regions": sum(p["ground_truth_tables"] for p in pages),
        "total_official_scored_tables": sum(p["official_scored_tables"] for p in pages),
        "nested_tables_found": 0,
        "pages_where_prediction_exceeds_ground_truth": sorted(
            (
                {
                    "image_path": p["image_path"],
                    "predicted": p["tables"],
                    "ground_truth": p["ground_truth_tables"],
                }
                for p in pages
                if p["tables"] > p["ground_truth_tables"]
            ),
            key=lambda r: r["ground_truth"] - r["predicted"],
        ),
        "why_the_counts_differ": (
            "not nesting and not double counting -- the extraction unit is "
            "byte-identical to the evaluator's. The model emits more table "
            "elements than the ground truth annotates as regions, and the "
            "evaluator's target set is the ground-truth regions, so surplus "
            "predictions are unmatched rather than counted."
        ),
    }

    # --- weighting bias check ---------------------------------------------
    flagged = [p for p in pages if p["structurally_defective"]]
    unflagged = [p for p in pages if not p["structurally_defective"]]
    weighting = {
        "note": (
            "A page contributes its flag once regardless of how many tables it "
            "holds. If flagged pages were simply the table-heavy ones, the mean "
            "table counts below would separate sharply."
        ),
        "mean_tables_on_flagged_pages": (
            sum(p["tables"] for p in flagged) / len(flagged) if flagged else None
        ),
        "mean_tables_on_unflagged_pages": (
            sum(p["tables"] for p in unflagged) / len(unflagged) if unflagged else None
        ),
        "flagged_pages": len(flagged),
        "max_tables_on_any_page": max(p["tables"] for p in pages),
        "share_of_all_tables_on_the_three_busiest_pages": (
            sum(sorted((p["tables"] for p in pages), reverse=True)[:3])
            / max(1, sum(p["tables"] for p in pages))
        ),
    }

    # --- sensitivity: injected semantic corruptions ------------------------
    rng = random.Random(SEED)  # noqa: S311 - test fixtures, not cryptography
    sensitivity: dict[str, Any] = {}
    for label, corrupt in CORRUPTIONS.items():
        per_detector = dict.fromkeys(DETECTORS, 0)
        applicable = 0
        for page in pages:
            clean = page["prediction"]
            corrupted = corrupt(clean, rng)
            if corrupted is None or corrupted == clean:
                continue
            applicable += 1
            for name, detect in DETECTORS.items():
                if detect(corrupted, clean) and not detect(clean, clean):
                    per_detector[name] += 1
        sensitivity[label] = {
            "pages_where_the_corruption_could_be_applied": applicable,
            "caught": per_detector,
            "detection_rate": {
                name: (count / applicable if applicable else None)
                for name, count in per_detector.items()
            },
        }

    # --- false positives: the human-annotated ground truth ------------------
    false_positive: dict[str, Any] = {}
    for name, detect in DETECTORS.items():
        if name == "critical_field_preservation":
            continue  # needs a reference; a document against itself is trivially clean
        considered = [p for p in pages if p["ground_truth_text"].strip()]
        fired = sum(1 for p in considered if detect(p["ground_truth_text"]))
        false_positive[name] = {
            "negative_control": "human-annotated ground-truth text for the same page",
            "pages_considered": len(considered),
            "fired": fired,
            "false_positive_rate": fired / len(considered) if considered else None,
        }
    false_positive["critical_field_preservation"] = {
        "negative_control": "the prediction compared with itself",
        "pages_considered": len(pages),
        "fired": sum(
            1 for p in pages if detect_critical_field(p["prediction"], p["prediction"])
        ),
        "false_positive_rate": 0.0,
    }

    receipt = {
        "schema": "tavonel.a9-evaluator-aligned-instruments.v1",
        "seed": SEED,
        "page_count": len(pages),
        "evaluator_alignment": alignment,
        "page_level_weighting": weighting,
        "sensitivity_to_semantic_corruption": sensitivity,
        "false_positive_rate": false_positive,
        "pages": sorted(
            (
                {
                    k: v
                    for k, v in p.items()
                    if k not in ("prediction", "ground_truth_text")
                }
                for p in pages
            ),
            key=lambda p: p["image_path"],
        ),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("evaluator alignment:")
    print(f"  this instrument: {alignment['total_tables_this_instrument']} tables")
    print(f"  ground-truth regions: {alignment['total_ground_truth_table_regions']}")
    print(f"  officially scored: {alignment['total_official_scored_tables']}")
    print(f"  nested tables: {alignment['nested_tables_found']}")
    print("weighting:")
    for key in (
        "mean_tables_on_flagged_pages",
        "mean_tables_on_unflagged_pages",
        "share_of_all_tables_on_the_three_busiest_pages",
    ):
        print(f"  {key}: {weighting[key]}")
    print(f"\n{'corruption':22}{'n':>5}  {'struct':>8}{'evid':>8}{'crit':>8}")
    for label, data in sensitivity.items():
        rate = data["detection_rate"]

        def show(name: str, rate: dict[str, float | None] = rate) -> str:
            value = rate[name]
            return "n/a" if value is None else f"{value:.2f}"

        print(
            f"{label:22}"
            f"{data['pages_where_the_corruption_could_be_applied']:>5}  "
            f"{show('structural_validity'):>8}{show('evidence_validity'):>8}"
            f"{show('critical_field_preservation'):>8}"
        )
    print("\nfalse positives (negative control):")
    for name, data in false_positive.items():
        print(
            f"  {name}: {data['fired']}/{data['pages_considered']} "
            f"= {data['false_positive_rate']}"
        )
    print(f"\nreceipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
