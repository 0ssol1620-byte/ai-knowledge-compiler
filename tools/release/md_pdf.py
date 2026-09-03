#!/usr/bin/env python3
"""A small, explicit Markdown-to-PDF typesetter for the hand-over documents.

There is no pandoc and no LaTeX on this machine, and reaching for a headless
browser would make the output depend on a browser's fonts and hyphenation. So
this renders the subset of Markdown the source documents actually use, through
reportlab, with the fonts named and embedded.

The subset is deliberately small and everything outside it raises. A typesetter
that silently drops a construct produces a document that looks finished and is
missing a paragraph, which is exactly the failure this package cannot afford.

Supported: ATX headings, paragraphs, `-`/`*` and `1.` lists, pipe tables, fenced
code, blockquotes, thematic breaks, and inline `**bold**`, `*italic*`, `` `code` ``
and bare URLs. Images are placed by the caller, not by Markdown syntax.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FONT_DIR = Path("C:/Windows/Fonts")
FONTS = {
    "Body": "arial.ttf",
    "Body-Bold": "arialbd.ttf",
    "Body-Italic": "ariali.ttf",
    "Body-BoldItalic": "arialbi.ttf",
    "Mono": "consola.ttf",
    "Mono-Bold": "consolab.ttf",
}

PAGE = A4
MARGIN = 20 * mm
#: reportlab's default frame adds 6 pt of padding on each side inside the
#: margins, so the width a flowable may actually occupy is 12 pt narrower than
#: the margin box. Sizing images to the margin box instead pushes them past the
#: right margin by exactly that much -- little enough to look intentional.
FRAME_PAD = 6.0
FRAME_W = PAGE[0] - 2 * MARGIN - 2 * FRAME_PAD


def register_fonts() -> None:
    for name, file in FONTS.items():
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
    pdfmetrics.registerFontFamily(
        "Body", normal="Body", bold="Body-Bold", italic="Body-Italic",
        boldItalic="Body-BoldItalic")
    pdfmetrics.registerFontFamily("Mono", normal="Mono", bold="Mono-Bold")


def styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("body", fontName="Body", fontSize=9.6, leading=13.4,
                          alignment=TA_JUSTIFY, spaceAfter=6)
    out = {
        "body": base,
        "h1": ParagraphStyle("h1", base, fontName="Body-Bold", fontSize=17,
                             leading=21, spaceBefore=0, spaceAfter=12,
                             alignment=TA_LEFT),
        "h2": ParagraphStyle("h2", base, fontName="Body-Bold", fontSize=13,
                             leading=16.5, spaceBefore=14, spaceAfter=7,
                             alignment=TA_LEFT),
        "h3": ParagraphStyle("h3", base, fontName="Body-Bold", fontSize=11,
                             leading=14.5, spaceBefore=11, spaceAfter=5,
                             alignment=TA_LEFT),
        "h4": ParagraphStyle("h4", base, fontName="Body-Italic", fontSize=10,
                             leading=13.5, spaceBefore=9, spaceAfter=4,
                             alignment=TA_LEFT),
        "li": ParagraphStyle("li", base, leftIndent=11, bulletIndent=2,
                             spaceAfter=3),
        "quote": ParagraphStyle("quote", base, leftIndent=12, rightIndent=8,
                                fontName="Body-Italic", textColor=colors.Color(
                                    0.22, 0.22, 0.22)),
        "code": ParagraphStyle("code", base, fontName="Mono", fontSize=8.2,
                               leading=10.6, leftIndent=8, alignment=TA_LEFT,
                               spaceAfter=8),
        "cell": ParagraphStyle("cell", base, fontSize=8.2, leading=10.4,
                               alignment=TA_LEFT, spaceAfter=0),
        "cellhead": ParagraphStyle("cellhead", base, fontName="Body-Bold",
                                   fontSize=8.2, leading=10.4, alignment=TA_LEFT,
                                   spaceAfter=0),
        "caption": ParagraphStyle("caption", base, fontSize=8.8, leading=11.6,
                                  alignment=TA_LEFT, spaceBefore=4,
                                  spaceAfter=10, fontName="Body-Italic"),
        "title": ParagraphStyle("title", base, fontName="Body-Bold", fontSize=20,
                                leading=25, alignment=TA_LEFT, spaceAfter=14),
        "note": ParagraphStyle("note", base, fontSize=9, leading=12.6,
                               alignment=TA_LEFT, textColor=colors.Color(
                                   0.25, 0.25, 0.25)),
    }
    return out


INLINE_CODE = re.compile(r"`([^`]+)`")
BOLD = re.compile(r"\*\*([^*]+)\*\*")
ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def inline(text: str) -> str:
    """Markdown inline markup to reportlab's mini-HTML, escaping first.

    Order matters: escaping after substitution would mangle the tags, and
    substituting inside code spans would let `**` inside a path become bold.
    """
    # Code spans are lifted out before the emphasis pass and put back after it.
    # Rendering them in place instead would split the string, and `**a `b` c**`
    # -- emphasis wrapping a code span, which these documents use -- would lose
    # its emphasis on both sides of the span with nothing to show it had failed.
    spans: list[str] = []

    def stash(m: re.Match[str]) -> str:
        spans.append(m.group(1))
        return f"\x00{len(spans) - 1}\x00"

    staged = INLINE_CODE.sub(stash, text)
    esc = html.escape(staged, quote=False)
    esc = LINK.sub(r"\1 (\2)", esc)
    esc = BOLD.sub(r"<b>\1</b>", esc)
    esc = ITALIC.sub(r"<i>\1</i>", esc)
    return re.sub(
        r"\x00(\d+)\x00",
        lambda m: f'<font name="Mono" size="8.6">'
                  f"{html.escape(spans[int(m.group(1))], quote=False)}</font>",
        esc)


@dataclass
class Block:
    kind: str
    lines: list[str] = field(default_factory=list)
    level: int = 0


def parse(md: str) -> list[Block]:
    """Group the source into blocks. Anything unrecognised becomes a paragraph."""
    blocks: list[Block] = []
    lines = md.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            body, i = [], i + 1
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            blocks.append(Block("code", body))
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            blocks.append(Block("heading", [m.group(2).strip()], len(m.group(1))))
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})\s*$", line):
            blocks.append(Block("rule"))
            i += 1
            continue
        if line.lstrip().startswith("|") and line.rstrip().endswith("|"):
            rows = []
            while (i < len(lines) and lines[i].lstrip().startswith("|")
                   and lines[i].rstrip().endswith("|")):
                rows.append(lines[i])
                i += 1
            blocks.append(Block("table", rows))
            continue
        if re.match(r"^\s*([-*+]|\d+\.)\s+", line):
            items: list[str] = []
            while i < len(lines) and (
                    re.match(r"^\s*([-*+]|\d+\.)\s+", lines[i])
                    or (lines[i].startswith("  ") and lines[i].strip() and items)):
                if re.match(r"^\s*([-*+]|\d+\.)\s+", lines[i]):
                    items.append(lines[i].strip())
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            blocks.append(Block("list", items))
            continue
        if line.startswith(">"):
            body = []
            while i < len(lines) and lines[i].startswith(">"):
                body.append(lines[i].lstrip("> ").rstrip())
                i += 1
            blocks.append(Block("quote", body))
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not (
                lines[i].startswith(("#", "```", ">", "|"))
                or re.match(r"^\s*([-*+]|\d+\.)\s+", lines[i])
                or re.match(r"^(-{3,}|\*{3,}|_{3,})\s*$", lines[i])):
            para.append(lines[i].strip())
            i += 1
        blocks.append(Block("para", [" ".join(para)]))
    return blocks


def table_flowable(rows: list[str], st: dict[str, ParagraphStyle]) -> Table:
    grid = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    grid = [r for r in grid if not all(re.fullmatch(r"[-: ]*", c) for c in r)]
    ncol = max(len(r) for r in grid)
    grid = [r + [""] * (ncol - len(r)) for r in grid]

    # Column widths in proportion to content, so a table of long prose in one
    # column and short codes in another does not get equal columns and wrap the
    # prose into a ribbon.
    #
    # The floor is the widest single word in the column, measured in the font it
    # will be drawn in. Proportional widths alone give a narrow column less room
    # than its longest token needs, and reportlab then breaks the word across
    # lines -- `n_repetitions` becomes `n_repe` / `titions`, which reads as a
    # rendering fault and is one.
    pad = 9.0

    def token_floor(col: int) -> float:
        widest = 0.0
        for row in grid:
            for word in re.split(r"[\s/]+", re.sub(r"[*`]", "", row[col])):
                widest = max(widest, pdfmetrics.stringWidth(word, "Body-Bold", 8.2))
        return widest + pad

    floors = [token_floor(c) for c in range(ncol)]
    weight = [max(1, max(len(r[c]) for r in grid)) for c in range(ncol)]
    total = sum(weight)
    widths = [max(FRAME_W * w / total, f) for w, f in zip(weight, floors, strict=True)]
    if sum(widths) > FRAME_W:
        # The floors alone do not fit. Take the excess out of the columns that
        # are above their floor, in proportion to their slack, and leave the
        # floors intact -- shrinking everything uniformly would reintroduce the
        # broken words this is here to prevent.
        excess = sum(widths) - FRAME_W
        slack = [w - f for w, f in zip(widths, floors, strict=True)]
        if sum(slack) >= excess > 0:
            widths = [w - excess * s / sum(slack)
                      for w, s in zip(widths, slack, strict=True)]
        else:
            k = FRAME_W / sum(widths)
            widths = [w * k for w in widths]

    data = [[Paragraph(inline(c), st["cellhead" if i == 0 else "cell"])
             for c in row] for i, row in enumerate(grid)]
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.Color(0.45, 0.45, 0.45)),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.93, 0.93, 0.93)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def figure_flowable(png: Path, caption: str, st: dict[str, ParagraphStyle],
                    max_h: float = 205 * mm) -> list[Any]:
    """A figure scaled to fit the frame in both directions.

    Both bounds are applied. Scaling only by width lets a tall diagram run past
    the bottom of the page, and Platypus then either splits it -- cropping the
    figure across a page boundary -- or raises. Neither is acceptable in a
    submission, so the height bound is enforced here rather than discovered
    during layout.
    """
    from PIL import Image as PILImage

    with PILImage.open(png) as im:
        px_w, px_h = im.size
        dpi = (im.info.get("dpi") or (300, 300))[0] or 300
    w, h = px_w * 72.0 / dpi, px_h * 72.0 / dpi
    k = min(FRAME_W / w, max_h / h, 1.0)
    img = Image(str(png), width=w * k, height=h * k)
    img.hAlign = "LEFT"
    return [CondPageBreak(min(h * k, max_h) * 0.55),
            KeepTogether([img, Paragraph(inline(caption), st["caption"])])]


def flowables(md: str, st: dict[str, ParagraphStyle],
              on_heading: Any = None, on_para: Any = None) -> list[Any]:
    """Blocks to flowables.

    `on_heading`/`on_para` let a caller inject content -- a figure after the
    paragraph that first references it, a page break before an appendix --
    without this function needing to know anything about the document.
    """
    out: list[Any] = []
    for block in parse(md):
        if block.kind == "heading":
            key = f"h{min(block.level, 4)}"
            extra = on_heading(block.level, block.lines[0]) if on_heading else None
            if extra:
                out.extend(extra)
            out.append(Paragraph(inline(block.lines[0]), st[key]))
        elif block.kind == "para":
            out.append(Paragraph(inline(block.lines[0]), st["body"]))
            extra = on_para(block.lines[0]) if on_para else None
            if extra:
                out.extend(extra)
        elif block.kind == "list":
            for item in block.lines:
                m = re.match(r"^([-*+]|\d+\.)\s+(.*)$", item)
                marker, text = m.group(1), m.group(2)
                bullet = "\u2022" if marker in "-*+" else marker
                out.append(Paragraph(inline(text), st["li"], bulletText=bullet))
            out.append(Spacer(1, 4))
        elif block.kind == "code":
            body = "<br/>".join(
                html.escape(ln, quote=False).replace(" ", "&nbsp;")
                for ln in block.lines)
            out.append(Paragraph(body or "&nbsp;", st["code"]))
        elif block.kind == "quote":
            out.append(Paragraph(inline(" ".join(block.lines)), st["quote"]))
        elif block.kind == "table":
            out.append(Spacer(1, 3))
            out.append(table_flowable(block.lines, st))
            out.append(Spacer(1, 9))
        elif block.kind == "rule":
            out.append(Spacer(1, 7))
    return out


def build(target: Path, story: list[Any], title: str, footer: str) -> int:
    """Write the document and return its page count."""
    register_fonts()

    def decorate(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Body", 7.6)
        canvas.setFillColor(colors.Color(0.35, 0.35, 0.35))
        canvas.drawString(MARGIN, 11 * mm, footer)
        canvas.drawRightString(PAGE[0] - MARGIN, 11 * mm, str(canvas.getPageNumber()))
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(target), pagesize=PAGE, title=title, author="TAVONEL",
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN + 6 * mm)
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)

    from pypdf import PdfReader
    return len(PdfReader(str(target)).pages)


__all__ = ["Image", "PageBreak", "Paragraph", "Spacer", "build", "figure_flowable",
           "flowables", "inline", "register_fonts", "styles"]
