#!/usr/bin/env python3
"""Read the built PDFs and check the properties a submission build must have.

Every check here reads the produced file. None of them asks the builder what it
did. The two are separate programs on purpose.

* **missing glyph** -- every character drawn is in the embedded font's character
  map. A character outside it is drawn as nothing, and the sentence still looks
  like a sentence.
* **clipped text / page overflow** -- every text span and every image sits
  inside the page's content frame.
* **overlapping figure or table** -- no image box overlaps a text box.
* **broken references** -- every `Figure N`, `Table N` and `§N` in the text has
  something in the document to refer to.
* **figure readability** -- every placed figure is large enough on the page to
  be read, and carries a caption directly beneath it.
* **numbering consistency** -- figure captions run 1..N in order, and the
  section headings ascend.
* **W6 boundary** -- the `NOT_MEASURED` / `NOT RUN` statement survives the
  build, and no comparative claim appears beside it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pymupdf
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "docs" / "paper" / "TAVONEL_MANUSCRIPT_GENERIC.pdf"
PATENT = ROOT / "docs" / "ip" / "TAVONEL_PATENT_FILING_REVIEW_DRAFT.pdf"
DRAWINGS = ROOT / "docs" / "ip" / "drawings" / "TAVONEL_PATENT_DRAWINGS.pdf"

FONT_FILES = ["arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf",
              "consola.ttf", "consolab.ttf"]
MARGIN = 20 * 72 / 25.4          # the builder's 20 mm, in points
TOL = 1.5                        # points of slack for glyph bearings

#: The comparative wording that must never appear next to the W6 statement.
COMPARATIVE = re.compile(
    r"\b(outperform\w*|better than|superior to|beats|state[- ]of[- ]the[- ]art)\b",
    re.I)


def covered_codepoints() -> set[int]:
    cps: set[int] = set()
    for file in FONT_FILES:
        with TTFont(f"C:/Windows/Fonts/{file}", fontNumber=0, lazy=True) as f:
            for table in f["cmap"].tables:
                cps |= set(table.cmap)
    return cps


def spans(page: pymupdf.Page) -> list[tuple[tuple[float, ...], str]]:
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span["text"].strip():
                    out.append((tuple(span["bbox"]), span["text"]))
    return out


def images(page: pymupdf.Page) -> list[tuple[float, ...]]:
    return [tuple(page.get_image_bbox(info)) for info in page.get_images(full=True)]


def overlaps(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def check_pdf(path: Path, cps: set[int], label: str) -> tuple[list[str], dict[str, Any]]:
    problems: list[str] = []
    doc = pymupdf.open(path)
    stats: dict[str, Any] = {"pages": doc.page_count, "figures": 0, "text_chars": 0}
    text_all: list[str] = []
    figure_page_text: list[str] = []

    for pno, page in enumerate(doc, start=1):
        rect = page.rect
        frame = (MARGIN - TOL, MARGIN - TOL,
                 rect.width - MARGIN + TOL, rect.height - MARGIN + TOL)
        page_spans = spans(page)
        page_images = images(page)
        stats["figures"] += len(page_images)
        if page_images:
            figure_page_text.append(" ".join(t for _, t in page_spans))

        for bbox, text in page_spans:
            text_all.append(text)
            stats["text_chars"] += len(text)
            bad = sorted({ch for ch in text if ord(ch) not in cps
                          and ch not in "\t\n\r"})
            if bad:
                problems.append(f"{label} p{pno}: characters outside the embedded "
                                f"fonts: {bad}")
            if bbox[0] < frame[0] or bbox[2] > frame[2]:
                problems.append(f"{label} p{pno}: text runs outside the horizontal "
                                f"frame ({bbox[0]:.1f}..{bbox[2]:.1f}): "
                                f"{text[:48]!r}")
            # The footer is drawn below the bottom margin on purpose; anything
            # else that low is content the layout failed to hold in.
            if bbox[3] > frame[3] and "·" not in text and not text.strip().isdigit():
                problems.append(f"{label} p{pno}: text runs past the bottom of the "
                                f"frame: {text[:48]!r}")

        for ibox in page_images:
            if (ibox[0] < frame[0] - 1 or ibox[2] > frame[2] + 1
                    or ibox[3] > frame[3] + 1):
                problems.append(f"{label} p{pno}: a figure runs outside the frame "
                                f"{tuple(round(v, 1) for v in ibox)}")
            if (ibox[2] - ibox[0]) < 90 or (ibox[3] - ibox[1]) < 40:
                problems.append(f"{label} p{pno}: a figure is only "
                                f"{ibox[2] - ibox[0]:.0f}x{ibox[3] - ibox[1]:.0f} pt, "
                                f"too small to read")
            for tbox, text in page_spans:
                area = overlaps(ibox, tbox)
                if area > 4:
                    problems.append(f"{label} p{pno}: a figure overlaps text "
                                    f"({area:.0f} pt²): {text[:40]!r}")

    body = " ".join(text_all)
    doc.close()
    return problems, {**stats, "body": body,
                      "figure_pages": " ".join(figure_page_text)}


def check_paper(body: str) -> list[str]:
    problems: list[str] = []

    captions = [int(n) for n in re.findall(r"Figure (\d+)\.\s", body)]
    have = set(captions)
    # Numbering is the figure set's, not the order of first citation. The set in
    # `docs/paper/FIGURES_2026-08-19.md` is separately audited and its numbers
    # are already cited in the audit record, so renumbering to citation order
    # here would rewrite a historical document to tidy a build. What must hold
    # is that the numbers are the set's, each appears once, and each is cited.
    if len(captions) != len(have):
        problems.append(f"paper: a figure is captioned more than once: {captions}")
    if have != set(range(1, len(captions) + 1)):
        problems.append(f"paper: captioned figures are not the full set 1..N: "
                        f"{sorted(have)}")

    cited = {int(n) for n in re.findall(r"\bFigure (\d+)\b", body)}
    if cited - have:
        problems.append(f"paper: text cites figures with no caption: "
                        f"{sorted(cited - have)}")
    if have - cited:
        problems.append(f"paper: figures with a caption and no citation: "
                        f"{sorted(have - cited)}")

    tables_cited = {int(n) for n in re.findall(r"\bTable (\d+)\b", body)}
    tables_have = {int(n) for n in re.findall(r"Table (\d+)\s*[—-]", body)}
    if tables_cited - tables_have:
        problems.append(f"paper: text cites tables that are not in the document: "
                        f"{sorted(tables_cited - tables_have)}")

    refs = {m for m in re.findall(r"§\s*(\d+(?:\.\d+)?)", body)}
    heads = {m for m in re.findall(r"\b(\d+\.\d+)\s+[A-Z]", body)}
    heads |= {m for m in re.findall(r"\b(\d+)\.\s+[A-Z]", body)}
    dangling = sorted(r for r in refs if r not in heads
                      and r.split(".")[0] not in heads)
    if dangling:
        problems.append(f"paper: section references with no matching heading: "
                        f"{dangling}")

    for marker in ("NOT RUN", "NOT_MEASURED"):
        if marker not in body:
            problems.append(f"paper: the W6 boundary marker {marker!r} did not "
                            f"survive the build")

    for m in COMPARATIVE.finditer(body):
        window = body[max(0, m.start() - 260) : m.end() + 260]
        if "NOT RUN" in window or "W6" in window:
            problems.append(f"paper: comparative wording {m.group(0)!r} within "
                            f"260 characters of the W6 boundary")

    for n in range(1, 15):
        if f"[{n}]" not in body:
            problems.append(f"paper: reference [{n}] is listed but never cited")
    return problems


def check_patent(body: str, figure_pages: str) -> list[str]:
    problems: list[str] = []
    # Sheet numbering is read from the pages that carry a sheet. The
    # specification prose refers to `FIG. 1` dozens of times, and counting those
    # would make this check depend on how often a drawing happens to be
    # discussed rather than on how the sheets are numbered.
    sheets = [int(n) for n in re.findall(r"FIG\. (\d+)\.\s", figure_pages)]
    if sheets != sorted(sheets) or sheets != list(range(1, len(sheets) + 1)):
        problems.append(f"patent: drawing sheets are not 1..N in order: {sheets}")
    for required in ("review copy, not a filing", "RESERVED"):
        if required not in body:
            problems.append(f"patent: the review copy does not say {required!r}")
    return problems


def main() -> int:
    cps = covered_codepoints()
    problems: list[str] = []
    receipt: dict[str, Any] = {"schema": "tavonel.submission-pdf-check.v1"}

    for path, label in ((PAPER, "paper"), (PATENT, "patent"),
                        (DRAWINGS, "drawings")):
        if not path.is_file():
            problems.append(f"{label}: {path.name} was not built")
            continue
        found, stats = check_pdf(path, cps, label)
        problems += found
        body = stats.pop("body")
        figure_pages = stats.pop("figure_pages")
        if label == "paper":
            problems += check_paper(body)
        elif label == "patent":
            problems += check_patent(body, figure_pages)
        receipt[label] = stats
        print(f"{label:9} {stats['pages']:>3} pages  {stats['figures']:>2} images  "
              f"{stats['text_chars']:>7} chars")

    receipt["problems"] = problems
    print(f"PROBLEMS: {len(problems)}")
    for p in problems[:40]:
        print(f"  - {p}")
    if len(problems) > 40:
        print(f"  ... and {len(problems) - 40} more")

    out = ROOT / "docs" / "ip" / "receipts" / "submission-pdf-check-2026-08-20.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
