#!/usr/bin/env python3
"""Two output-only instruments, rebuilt, and validated before they are believed.

The first versions of both returned a constant across all 200 pages and that
constant was reported as "no signal". It was not: the structural check looked for
ragged markdown pipe tables while this model emits HTML (`<table>` 87 times and
`<td>` 3,163 times across the ten pages that have tables, and markdown pipe rows
zero times), and the consistency check compared the output with a whitespace-
normalised copy of itself, a transform that cannot move a number. Neither
instrument ever touched what it claimed to measure.

So this rebuilds both against the format the model actually emits, and then --
before any proxy performance is reported -- validates each one two ways:

  * **against the corpus**, by checking the tables it finds against the tables
    the ground truth and the official evaluator agree are there;
  * **against injected defects**, by taking clean real outputs, introducing one
    known corruption of each kind, and requiring the instrument to notice. An
    instrument that cannot catch a defect placed in front of it cannot be
    trusted when it reports none.

The injections exist to test the instrument. They are never a performance
result, and no number from them describes the model.

`evidence_validity` deliberately does not compare with a source. Nothing here has
one at inference time. It checks whether the semantic-critical fields the output
*states* are internally well formed -- a date that exists, a currency amount that
has an amount, a number that parses, a table whose rows agree on their width.
A page can be wrong and pass; it cannot be right and fail.
"""

from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]

MONTH_DAY = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
MALFORMED_NUMBER = re.compile(r"\d[\d,]*\.{2,}\d|\d,\d{1,2}\b(?!\d)|(?<![\d.])\.\d+\.\d")
ORPHAN_CURRENCY = re.compile(r"[$€£¥](?!\s?[\d(])")
DOUBLE_SIGN = re.compile(r"(?<![\d\w])[-+]{2,}\d")
DAYS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

# LaTeX math spans, removed before any evidence rule runs. The first version of
# `orphan_currency` fired on 42 of 200 ground-truth documents, and every one was
# a math delimiter rather than a currency symbol -- this corpus writes prices as
# `$\$$6-$\$$18`, so the opening `$` of a math span looked like a currency
# symbol with no amount after it. A detector that fires on a quarter of
# known-good documents is measuring the corpus's typesetting, not its defects.
MATH_SPAN = re.compile(
    r"\$\$.*?\$\$"          # display math
    r"|\$(?!\$).*?\$"       # inline math
    r"|\\\(.*?\\\)"         # \( ... \)
    r"|\\\[.*?\\\]",        # \[ ... \]
    re.DOTALL,
)


def without_math(markup: str) -> str:
    """Blank out LaTeX math spans, preserving offsets so counts stay comparable."""
    return MATH_SPAN.sub(lambda m: " " * (m.end() - m.start()), markup)


class TableShapes(HTMLParser):
    """Row widths per table, counting colspan, tolerating unclosed tags.

    A real parser rather than a regex: the model nests tables and omits closing
    tags, and a regex that appears to work on the clean pages is exactly the kind
    of instrument this file exists to stop trusting.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[int]] = []
        self.stack: list[list[int]] = []
        self.row_width: int | None = None
        self.cells = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.stack.append([])
        elif tag == "tr" and self.stack:
            self.row_width = 0
        elif tag in ("td", "th") and self.stack and self.row_width is not None:
            span = 1
            for name, value in attrs:
                if name == "colspan" and value and value.isdigit():
                    span = max(1, int(value))
            self.row_width += span
            self.cells += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self.stack and self.row_width is not None:
            self.stack[-1].append(self.row_width)
            self.row_width = None
        elif tag == "table" and self.stack:
            self.tables.append(self.stack.pop())

    def close(self) -> None:  # unclosed tables still count
        super().close()
        while self.stack:
            self.tables.append(self.stack.pop())


def table_shapes(markup: str) -> tuple[list[list[int]], int]:
    parser = TableShapes()
    parser.feed(markup)
    parser.close()
    return parser.tables, parser.cells


def structural_defects(markup: str) -> dict[str, Any]:
    tables, cells = table_shapes(markup)
    ragged = [shape for shape in tables if len(set(shape)) > 1]
    empty = [shape for shape in tables if not shape]
    headings = re.findall(r"^\s*#{1,6}\s*(.*)$", markup, flags=re.MULTILINE)
    return {
        "tables": len(tables),
        "table_cells": cells,
        "ragged_tables": len(ragged),
        "empty_tables": len(empty),
        "empty_headings": sum(1 for h in headings if not h.strip()),
        "unbalanced_table_tags": abs(
            markup.count("<table") - markup.count("</table>")
        ),
    }


def structural_validity(markup: str) -> float:
    defects = structural_defects(markup)
    considered = max(1, defects["tables"] + len(re.findall(r"^\s*#", markup, re.M)))
    found = (
        defects["ragged_tables"]
        + defects["empty_tables"]
        + defects["empty_headings"]
        + defects["unbalanced_table_tags"]
    )
    return max(0.0, 1.0 - found / considered)


def evidence_defects(markup: str) -> dict[str, Any]:
    markup = without_math(markup)
    impossible_dates = 0
    for month, day, _ in MONTH_DAY.findall(markup):
        m, d = int(month), int(day)
        if m == 0 or m > 12 or d == 0 or d > DAYS[min(m, 12) - 1]:
            impossible_dates += 1
    for year, month, day in ISO_DATE.findall(markup):
        m, d = int(month), int(day)
        if m == 0 or m > 12 or d == 0 or d > DAYS[min(m, 12) - 1] or int(year) == 0:
            impossible_dates += 1
    return {
        "impossible_dates": impossible_dates,
        "malformed_numbers": len(MALFORMED_NUMBER.findall(markup)),
        "orphan_currency_symbols": len(ORPHAN_CURRENCY.findall(markup)),
        "double_signs": len(DOUBLE_SIGN.findall(markup)),
    }


def evidence_validity(markup: str) -> float:
    defects = sum(evidence_defects(markup).values())
    return 1.0 / (1.0 + defects)


# --- instrument validation -------------------------------------------------

def inject_ragged_table(markup: str) -> str | None:
    index = markup.find("</td>")
    return markup[:index] + "</td><td>injected</td>" + markup[index + 5 :] if index > 0 else None


def inject_impossible_date(markup: str) -> str:
    return markup + "\n\nRevised 13/45/2026.\n"


def inject_malformed_number(markup: str) -> str:
    return markup + "\n\nTotal 12..7 units.\n"


def inject_orphan_currency(markup: str) -> str:
    return markup + "\n\nPrice $ each.\n"


def inject_double_sign(markup: str) -> str:
    return markup + "\n\nChange --5 percent.\n"


def validate_instruments(pages: list[tuple[str, str]]) -> dict[str, Any]:
    """Every injection must move its instrument. One that does not is broken."""
    with_tables = [(name, text) for name, text in pages if "<table" in text]
    results: dict[str, Any] = {}

    caught = considered = 0
    for _name, text in with_tables:
        injected = inject_ragged_table(text)
        if injected is None:
            continue
        considered += 1
        if structural_validity(injected) < structural_validity(text):
            caught += 1
    results["structural_ragged_table"] = {
        "pages_tested": considered,
        "caught": caught,
        "detection_rate": caught / considered if considered else None,
    }

    for label, injector in (
        ("impossible_date", inject_impossible_date),
        ("malformed_number", inject_malformed_number),
        ("orphan_currency", inject_orphan_currency),
        ("double_sign", inject_double_sign),
    ):
        caught = 0
        for _, text in pages:
            if evidence_validity(injector(text)) < evidence_validity(text):
                caught += 1
        results[f"evidence_{label}"] = {
            "pages_tested": len(pages),
            "caught": caught,
            "detection_rate": caught / len(pages),
        }
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--official-artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    samples = json.loads(args.ground_truth.resolve().read_text(encoding="utf-8"))
    official_teds = json.loads(
        (args.official_artifacts.resolve() / "table_per_table_TEDS.json").read_text(
            encoding="utf-8"
        )
    )
    official_tables_per_page: dict[str, int] = {}
    for key in official_teds:
        page = key.rsplit("_[", 1)[0] if key.endswith("]") and "_[" in key else key
        official_tables_per_page[page] = official_tables_per_page.get(page, 0) + 1

    pages: list[tuple[str, str]] = []
    records: list[dict[str, Any]] = []
    for sample in samples:
        image = str(sample["page_info"]["image_path"])
        text = (args.predictions.resolve() / f"{Path(image).stem}.md").read_text("utf-8")
        pages.append((image, text))
        gt_tables = sum(
            1 for item in sample["layout_dets"] if item.get("category_type") == "table"
        )
        records.append(
            {
                "image_path": image,
                "ground_truth_tables": gt_tables,
                "official_scored_tables": official_tables_per_page.get(image, 0),
                "structural_validity": structural_validity(text),
                "evidence_validity": evidence_validity(text),
                **structural_defects(text),
                **evidence_defects(text),
            }
        )

    # Does the instrument find tables where tables are?
    gt_pages = {r["image_path"] for r in records if r["ground_truth_tables"]}
    found_pages = {r["image_path"] for r in records if r["tables"]}
    corpus_check = {
        "pages_with_ground_truth_tables": len(gt_pages),
        "pages_where_instrument_found_a_table": len(found_pages),
        "agreement_on_which_pages_have_tables": len(gt_pages & found_pages),
        "instrument_found_none_where_ground_truth_has_tables": sorted(
            gt_pages - found_pages
        ),
        "total_ground_truth_tables": sum(r["ground_truth_tables"] for r in records),
        "total_official_scored_tables": sum(
            r["official_scored_tables"] for r in records
        ),
        "total_tables_instrument_found": sum(r["tables"] for r in records),
        "total_cells_instrument_found": sum(r["table_cells"] for r in records),
    }

    receipt = {
        "schema": "tavonel.a9-repaired-output-instruments.v1",
        "purpose": "instrument validation, not proxy performance",
        "why_rebuilt": (
            "the first structural instrument looked for markdown pipe tables and "
            "examined 0 tables across 200 pages while the official evaluator scored "
            "60; the first consistency instrument compared the output with a "
            "whitespace-normalised copy of itself, which cannot move a critical token"
        ),
        "corpus_validation": corpus_check,
        "injection_validation": validate_instruments(pages),
        "injection_note": (
            "Injections test the instrument. They are not a measurement of the model "
            "and no number from them may be reported as one."
        ),
        "page_count": len(records),
        "pages": sorted(records, key=lambda r: r["image_path"]),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print("corpus validation:")
    for key, value in corpus_check.items():
        print(f"  {key}: {value}")
    print("injection validation:")
    for key, value in receipt["injection_validation"].items():
        rate = value["detection_rate"]
        print(
            f"  {key}: {value['caught']}/{value['pages_tested']} "
            f"({'n/a' if rate is None else f'{rate:.2f}'})"
        )
    print(f"receipt: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
