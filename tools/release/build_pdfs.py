#!/usr/bin/env python3
"""Build the generic paper submission PDF and the patent filing review PDF.

Neither is a venue submission or a filing. The paper build is *generic*: A4,
single column, no venue template, because ACM/IEEE/NeurIPS formatting is chosen
after a venue is chosen. The patent build is a *review copy*: it carries the
title, abstract, specification, claims, drawing descriptions and the rendered
drawing sheets in one file so counsel can read the whole thing, and it says on
its own first page that claim numbering and jurisdiction filing form are not
settled here.

Both are built from the Markdown sources with no hand-edited intermediate, so
the PDF cannot drift from the document the audits read.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from md_pdf import (
    PageBreak,
    Paragraph,
    Spacer,
    build,
    figure_flowable,
    flowables,
    register_fonts,
    styles,
)

ROOT = Path(__file__).resolve().parents[2]
DATE = "2026-08-20"

MANUSCRIPT = ROOT / "docs" / "paper" / "MANUSCRIPT_v1_2026-08-19.md"
TABLES = ROOT / "docs" / "paper" / "TABLES_2026-08-19.md"
FIGURES_SPEC = ROOT / "docs" / "paper" / "FIGURES_2026-08-19.md"
REGISTRY = ROOT / "docs" / "paper" / "figures" / "FIGURE_REGISTRY.json"

PATENT_ABSTRACT = ROOT / "docs" / "ip" / "PATENT_ABSTRACT_AND_DRAWINGS_2026-08-20.md"
PATENT_SPEC = ROOT / "docs" / "ip" / "PATENT_SPECIFICATION_v1_2026-08-19.md"
PATENT_CLAIMS = ROOT / "docs" / "ip" / "PATENT_CLAIM_SET_v1_2026-08-19.md"

PAPER_PDF = ROOT / "docs" / "paper" / "TAVONEL_MANUSCRIPT_GENERIC.pdf"
PATENT_PDF = ROOT / "docs" / "ip" / "TAVONEL_PATENT_FILING_REVIEW_DRAFT.pdf"
DRAWINGS_PDF = ROOT / "docs" / "ip" / "drawings" / "TAVONEL_PATENT_DRAWINGS.pdf"
RECEIPT = ROOT / "docs" / "ip" / "receipts" / f"submission-pdf-build-{DATE}.json"

FIG_REF = re.compile(r"\bFigure (\d+)\b")


def figure_captions(spec: Path, pattern: str) -> dict[int, str]:
    text = spec.read_text(encoding="utf-8")
    return {int(m.group(1)): m.group(2).strip()
            for m in re.finditer(pattern, text, re.M)}


def paper_story() -> tuple[list[Any], dict[str, Any]]:
    st = styles()
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assets = {f["figure"]: ROOT / f["assets"]["png"]["path"] for f in reg["paper"]}
    captions = figure_captions(FIGURES_SPEC, r"^## Figure (\d+) — (.+)$")
    placed: set[int] = set()

    def after_para(text: str) -> list[Any]:
        """Place a figure immediately after the paragraph that first cites it.

        Placing figures at the end instead would be less work and would make the
        reader hold eight diagrams in their head; placing them at the citation
        is what the numbering in the text is for.
        """
        out: list[Any] = []
        for m in FIG_REF.finditer(text):
            n = int(m.group(1))
            if n in placed or n not in assets:
                continue
            placed.add(n)
            out += figure_flowable(assets[n], f"**Figure {n}.** {captions[n]}", st)
        return out

    story: list[Any] = [
        Paragraph("TAVONEL — generic submission build", st["note"]),
        Spacer(1, 4),
    ]
    story += flowables(MANUSCRIPT.read_text(encoding="utf-8"), st,
                       on_para=after_para)

    story.append(PageBreak())
    story.append(Paragraph("Appendix C — tables", st["h2"]))
    story.append(Paragraph(
        "Reproduced in full from <font name=\"Mono\" size=\"8.6\">"
        "docs/paper/TABLES_2026-08-19.md</font>, the file the manuscript cites. "
        "Table numbering is that file's.", st["note"]))
    story.append(Spacer(1, 6))
    tables_md = re.sub(r"^# .*$", "", TABLES.read_text(encoding="utf-8"), count=1,
                       flags=re.M)
    story += flowables(tables_md, st)

    missing = sorted(set(assets) - placed)
    return story, {"figures_placed": sorted(placed), "figures_unplaced": missing}


def patent_story() -> tuple[list[Any], dict[str, Any]]:
    st = styles()
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    sheets = {f["figure"]: ROOT / f["assets"]["png"]["path"] for f in reg["patent"]}
    captions = figure_captions(PATENT_ABSTRACT, r"^### FIG\. (\d+) — (.+)$")

    story: list[Any] = [
        Paragraph("TAVONEL — patent filing review draft", st["title"]),
        Paragraph(
            "<b>This is a review copy, not a filing.</b> It gathers the title, "
            "abstracts, specification, claim set, drawing descriptions and "
            "rendered drawing sheets into one document so that they can be read "
            "together. Claim numbering, dependency form, jurisdiction-specific "
            "drawing formalities, margins, sheet headers and the filing form "
            "itself are counsel's, and are not settled by this document. Claims "
            "marked RESERVED are disclosed here and are not part of the filing "
            "core; see the filing-group tables in the claim set.", st["note"]),
        Spacer(1, 6),
        Paragraph(f"Generated {DATE} from the repository sources named in each "
                  f"part heading. No content in this PDF was authored outside "
                  f"those sources.", st["note"]),
        PageBreak(),
    ]

    parts = [
        ("Part I — abstracts and drawing descriptions", PATENT_ABSTRACT),
        ("Part II — specification", PATENT_SPEC),
        ("Part III — claim set", PATENT_CLAIMS),
    ]
    for heading, src in parts:
        story.append(Paragraph(heading, st["h1"]))
        story.append(Paragraph(
            f'Source: <font name="Mono" size="8.6">'
            f"{src.relative_to(ROOT).as_posix()}</font>", st["note"]))
        story.append(Spacer(1, 8))
        body = src.read_text(encoding="utf-8")
        # The mermaid sources belong to the drawing sheets in Part IV; leaving
        # them here would print the diagram twice, once as code.
        body = re.sub(r"```mermaid\n.*?\n```", "", body, flags=re.S)
        story += flowables(body, st)
        story.append(PageBreak())

    story.append(Paragraph("Part IV — drawing sheets", st["h1"]))
    story.append(Paragraph(
        "Rendered from the same sources as the drawing descriptions in Part I. "
        "Monochrome line art with three-digit reference numerals. Every element "
        "drawn here appears in the specification and the claim set; the sheets "
        "introduce nothing that is not already recited there.", st["note"]))
    story.append(Spacer(1, 8))
    for n in sorted(sheets):
        story.append(Paragraph(f"FIG. {n}", st["h3"]))
        story += figure_flowable(sheets[n], f"**FIG. {n}.** {captions[n]}", st)
        story.append(PageBreak())
    story.pop()

    return story, {"sheets_placed": sorted(sheets)}


def drawings_only() -> int:
    """The drawing sheets on their own, one sheet per page, each labelled.

    A combined drawings PDF is what a draftsperson and a filing agent actually
    ask for, and it must be separable from the review copy.
    """
    st = styles()
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    sheets = {f["figure"]: ROOT / f["assets"]["png"]["path"] for f in reg["patent"]}
    captions = figure_captions(PATENT_ABSTRACT, r"^### FIG\. (\d+) — (.+)$")

    story: list[Any] = []
    for n in sorted(sheets):
        story.append(Paragraph(f"FIG. {n}", st["h2"]))
        story += figure_flowable(sheets[n], f"**FIG. {n}.** {captions[n]}", st)
        story.append(PageBreak())
    story.pop()
    DRAWINGS_PDF.parent.mkdir(parents=True, exist_ok=True)
    return build(DRAWINGS_PDF, story, "TAVONEL patent drawings",
                 f"TAVONEL patent drawings · {DATE} · review copy, not a filing")


def main() -> int:
    register_fonts()
    receipt: dict[str, Any] = {
        "schema": "tavonel.submission-pdf-build.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "note": "Generic build. Venue formatting and jurisdiction filing form "
                "are deliberately absent and are external actions.",
    }

    story, meta = paper_story()
    pages = build(PAPER_PDF, story, "TAVONEL — compiling organizational knowledge",
                  f"TAVONEL generic submission build · {DATE} · not venue-formatted")
    receipt["paper"] = {"path": PAPER_PDF.relative_to(ROOT).as_posix(),
                        "pages": pages, **meta}
    print(f"paper:    {pages} pages, figures placed {meta['figures_placed']}")
    if meta["figures_unplaced"]:
        print(f"  WARNING: figures never cited in the text: "
              f"{meta['figures_unplaced']}")

    story, meta = patent_story()
    pages = build(PATENT_PDF, story, "TAVONEL patent filing review draft",
                  f"TAVONEL patent review draft · {DATE} · not a filing")
    receipt["patent"] = {"path": PATENT_PDF.relative_to(ROOT).as_posix(),
                         "pages": pages, **meta}
    print(f"patent:   {pages} pages, sheets {meta['sheets_placed']}")

    pages = drawings_only()
    receipt["drawings"] = {"path": DRAWINGS_PDF.relative_to(ROOT).as_posix(),
                           "pages": pages}
    print(f"drawings: {pages} pages")

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
    print(f"wrote {RECEIPT.relative_to(ROOT).as_posix()}")
    return 1 if meta.get("figures_unplaced") else 0


if __name__ == "__main__":
    sys.exit(main())
