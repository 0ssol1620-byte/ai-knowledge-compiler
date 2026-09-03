#!/usr/bin/env python3
"""Render the figure specifications into vector and raster assets.

The specifications are the source of truth. `docs/paper/FIGURES_2026-08-19.md`
and `docs/ip/PATENT_ABSTRACT_AND_DRAWINGS_2026-08-20.md` each carry the diagram
sources inline, and this tool extracts them, renders them, and records what it
produced. It never authors a diagram: a figure that exists only as a rendered
asset would be a figure no audit reads.

Two output families, and they are deliberately different:

* **paper** keeps the authored colours, because several figures use a coloured
  grouping to carry a distinction (evidence class, in Figure 6). Every coloured
  group also carries a text label, so the distinction survives greyscale
  printing -- and that property is asserted mechanically here rather than
  assumed.
* **patent** is forced monochrome line art. A drawing sheet with colour in it is
  a drawing sheet a draftsperson has to redo, and colour that carries meaning is
  a scope statement made outside the claims.

Requires `npx @mermaid-js/mermaid-cli`. Run from the repository root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PAPER_SPEC = ROOT / "docs" / "paper" / "FIGURES_2026-08-19.md"
PATENT_SPEC = ROOT / "docs" / "ip" / "PATENT_ABSTRACT_AND_DRAWINGS_2026-08-20.md"
PAPER_OUT = ROOT / "docs" / "paper" / "figures"
PATENT_OUT = ROOT / "docs" / "ip" / "drawings"
REGISTRY = ROOT / "docs" / "paper" / "figures" / "FIGURE_REGISTRY.json"

FIG_HEAD = re.compile(r"^## Figure (\d+) — (.+)$", re.M)
DRAW_HEAD = re.compile(r"^### FIG\. (\d+) — (.+)$", re.M)
MERMAID = re.compile(r"```mermaid\n(.*?)\n```", re.S)
TABLE_ROW = re.compile(r"^\|.*\|$", re.M)

#: Patent sheets are line art. `neutral` plus these variables removes every fill
#: and tint mermaid would otherwise apply, leaving black strokes on white.
PATENT_CONFIG = {
    "theme": "neutral",
    "themeVariables": {
        "background": "#ffffff",
        "primaryColor": "#ffffff",
        "primaryTextColor": "#000000",
        "primaryBorderColor": "#000000",
        "lineColor": "#000000",
        "secondaryColor": "#ffffff",
        "tertiaryColor": "#ffffff",
        "mainBkg": "#ffffff",
        "nodeBorder": "#000000",
        "clusterBkg": "#ffffff",
        "clusterBorder": "#000000",
        "edgeLabelBackground": "#ffffff",
        "fontFamily": "Arial, Helvetica, sans-serif",
        "fontSize": "15px",
    },
    "flowchart": {"htmlLabels": True, "curve": "linear", "padding": 12},
}

PAPER_CONFIG = {
    "theme": "neutral",
    "themeVariables": {"fontFamily": "Arial, Helvetica, sans-serif", "fontSize": "15px"},
    "flowchart": {"htmlLabels": True, "curve": "basis", "padding": 12},
}


VIEWBOX = re.compile(r'viewBox="([-0-9.]+) ([-0-9.]+) ([0-9.]+) ([0-9.]+)"')


def intrinsic_width(svg: Path) -> float:
    m = VIEWBOX.search(svg.read_text(encoding="utf-8", errors="replace")[:2000])
    return float(m.group(3)) if m else 0.0


def pin_svg_size(svg: Path) -> tuple[float, float]:
    """Give the vector an intrinsic size instead of `width="100%"`.

    mermaid emits a fluid SVG: it fills whatever box it is dropped into, and its
    real dimensions live only in the viewBox. That is right for a web page and
    wrong for a submission asset, where the same file goes to a typesetter, a
    reviewer's viewer and a print pipeline, and each of them decides the size
    differently. Pinning width and height from the viewBox makes those three
    agree, and it is the size the raster's resolution is measured against.
    """
    text = svg.read_text(encoding="utf-8")
    m = VIEWBOX.search(text[:2000])
    if not m:
        return 0.0, 0.0
    w, h = float(m.group(3)), float(m.group(4))
    text = text.replace('width="100%"', f'width="{w:.2f}" height="{h:.2f}"', 1)
    text = re.sub(r"max-width:\s*[0-9.]+px;\s*", "", text, count=1)
    svg.write_text(text, encoding="utf-8")
    return w, h


#: Preview rasters are produced at this resolution against the vector's own size.
RASTER_DPI = 300


def stamp_dpi(svg: Path, png: Path) -> float:
    """Measure the raster's true resolution and write it into the file.

    A PNG that says 300 dpi in a README and carries no resolution of its own is
    a claim with nothing behind it. This divides the pixel width by the vector's
    width in inches and records the answer, so the number in the registry is a
    measurement of two files rather than a restatement of the flag passed to the
    renderer.
    """
    from PIL import Image

    width = intrinsic_width(svg)
    if not width:
        return 0.0
    inches = width / 96.0
    with Image.open(png) as im:
        dpi = im.size[0] / inches if inches else 0.0
        im.load()
        im.save(png, dpi=(dpi, dpi))
    return round(dpi, 1)


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def mmdc() -> list[str]:
    exe = shutil.which("npx") or shutil.which("npx.cmd")
    if not exe:
        raise RuntimeError("npx not found; mermaid-cli cannot be invoked")
    return [exe, "-y", "@mermaid-js/mermaid-cli@11.16.0", "-q"]


def render(source: Path, target: Path, config: Path,
           scale: float | None = None, width: int | None = None) -> None:
    cmd = [*mmdc(), "-i", str(source), "-o", str(target), "-c", str(config),
           "-b", "white"]
    if target.suffix == ".pdf":
        # Without --pdfFit the diagram is placed on a fixed page and a tall
        # figure paginates. A figure split across three pages is a figure that
        # arrives cropped, and it looks entirely normal until someone opens it.
        cmd += ["--pdfFit"]
    if width:
        # The renderer lays the diagram out in a viewport, and a diagram wider
        # than that viewport is rasterised against the viewport rather than
        # against itself -- silently, at a lower effective resolution. Setting
        # the viewport to the vector's own width is what makes the scale factor
        # mean what it says.
        cmd += ["--width", str(width)]
    if scale:
        cmd += ["--scale", str(scale)]
    result = subprocess.run(  # noqa: S603
        cmd, cwd=ROOT, capture_output=True, text=True, timeout=600, check=False)
    if result.returncode != 0 or not target.is_file():
        raise RuntimeError(
            f"mermaid-cli failed for {source.name} -> {target.name}: "
            f"{(result.stdout + result.stderr)[-800:]}")


def section_bodies(text: str, head: re.Pattern[str]) -> list[tuple[int, str, str]]:
    """(number, caption, body-up-to-the-next-heading-of-the-same-level)."""
    marks = list(head.finditer(text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((int(m.group(1)), m.group(2).strip(), text[m.end() : end]))
    return out


#: One geometry, three backends. A table figure is laid out once and drawn to
#: SVG, PDF and PNG from the same numbers, so the three assets are the same
#: figure rather than three near-misses. `PAD`/`LINE_H`/`FONT` are points; the
#: PNG scales all of them by a single factor to reach 300 dpi.
PAD, LINE_H, CHAR_W, FONT, TITLE_H = 10.0, 22.0, 7.2, 13.0, 30.0


def table_layout(rows: list[list[str]]) -> tuple[list[float], float, float]:
    widths = [max(CHAR_W * max(len(r[c]) for r in rows) + 2 * PAD, 90.0)
              for c in range(len(rows[0]))]
    return widths, sum(widths) + 2, LINE_H * len(rows) + 2 + TITLE_H + 4


def svg_table(rows: list[list[str]], title: str, target: Path) -> None:
    """A deterministic SVG table, for a figure whose specification is a table.

    Written rather than delegated because the alternative -- screenshotting a
    rendered page -- makes the asset depend on a browser's fonts and produces a
    raster where a vector is wanted. Column widths are computed from the longest
    cell so nothing is clipped, which is the property the figure check asserts.
    """
    pad, line_h, font = PAD, LINE_H, FONT
    widths, w, h = table_layout(rows)

    def esc(s: str) -> str:
        return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" '
        f'viewBox="0 0 {w:.0f} {h:.0f}" font-family="Arial, Helvetica, sans-serif">',
        f'<rect width="{w:.0f}" height="{h:.0f}" fill="#ffffff"/>',
        f'<text x="2" y="18" font-size="14" font-weight="bold">{esc(title)}</text>',
    ]
    y = 30.0
    for ri, row in enumerate(rows):
        x = 1.0
        weight = "bold" if ri == 0 else "normal"
        fill = "#f2f2f2" if ri == 0 else "#ffffff"
        for ci, cell in enumerate(row):
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{widths[ci]:.1f}" '
                f'height="{line_h}" fill="{fill}" stroke="#000000" stroke-width="1"/>')
            parts.append(
                f'<text x="{x + pad:.1f}" y="{y + line_h - 7:.1f}" font-size="{font}" '
                f'font-weight="{weight}">{esc(cell)}</text>')
            x += widths[ci]
        y += line_h
    parts.append("</svg>")
    target.write_text("\n".join(parts), encoding="utf-8")


def pdf_table(rows: list[list[str]], title: str, target: Path) -> list[str]:
    """The same table as vector PDF. Returns any cell whose text overruns its column.

    reportlab measures the string in the font it will actually draw, so this is a
    measurement of the produced page rather than a restatement of the layout
    heuristic that produced it.
    """
    from reportlab.lib.colors import Color
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas as rl_canvas

    for name, file in (("FigArial", "arial.ttf"), ("FigArial-Bold", "arialbd.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, f"C:/Windows/Fonts/{file}"))

    widths, w, h = table_layout(rows)
    c = rl_canvas.Canvas(str(target), pagesize=(w, h))
    c.setTitle(title)
    c.setFillColor(Color(1, 1, 1))
    c.rect(0, 0, w, h, stroke=0, fill=1)
    c.setFillColor(Color(0, 0, 0))
    c.setFont("FigArial-Bold", 14)
    c.drawString(2, h - 18, title)

    clipped: list[str] = []
    y = h - TITLE_H
    for ri, row in enumerate(rows):
        x, font = 1.0, "FigArial-Bold" if ri == 0 else "FigArial"
        y -= LINE_H
        for ci, cell in enumerate(row):
            c.setFillColor(Color(0.949, 0.949, 0.949) if ri == 0 else Color(1, 1, 1))
            c.setStrokeColor(Color(0, 0, 0))
            c.rect(x, y, widths[ci], LINE_H, stroke=1, fill=1)
            c.setFillColor(Color(0, 0, 0))
            c.setFont(font, FONT)
            c.drawString(x + PAD, y + 7, cell)
            if pdfmetrics.stringWidth(cell, font, FONT) > widths[ci] - 2 * PAD:
                clipped.append(f"r{ri}c{ci}: {cell!r}")
            x += widths[ci]
    c.showPage()
    c.save()
    return clipped


def png_table(rows: list[list[str]], title: str, target: Path, dpi: int = 300) -> None:
    """The same table rasterised at `dpi`, for previewing without a vector viewer."""
    from PIL import Image, ImageDraw, ImageFont

    k = dpi / 72.0
    widths, w, h = table_layout(rows)
    img = Image.new("RGB", (round(w * k), round(h * k)), "white")
    d = ImageDraw.Draw(img)
    reg = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", round(FONT * k))
    bold = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", round(FONT * k))
    d.text((2 * k, 4 * k), title,
           font=ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", round(14 * k)),
           fill="black")

    y = TITLE_H * k
    for ri, row in enumerate(rows):
        x = 1.0 * k
        for ci, cell in enumerate(row):
            d.rectangle([x, y, x + widths[ci] * k, y + LINE_H * k],
                        fill="#f2f2f2" if ri == 0 else "white", outline="black", width=1)
            d.text((x + PAD * k, y + 4 * k), cell, font=bold if ri == 0 else reg,
                   fill="black")
            x += widths[ci] * k
        y += LINE_H * k
    img.save(target, dpi=(dpi, dpi))


def parse_table(body: str) -> list[list[str]] | None:
    rows = [r for r in TABLE_ROW.findall(body) if not set(r) <= set("|-: ")]
    if len(rows) < 2:
        return None
    return [[c.strip().replace("**", "").replace("`", "") for c in r.strip("|").split("|")]
            for r in rows]


def greyscale_safety(source: str) -> dict[str, Any]:
    """Does every coloured group also carry a text label?

    Colour may distinguish groups on a paper figure. It may not be the *only*
    thing that distinguishes them, because a reviewer printing in black and white
    would then lose the distinction entirely. `style X fill:` names a node or
    subgraph id; a subgraph carries its label in brackets after the id.
    """
    styled = set(re.findall(r"^\s*style\s+(\w+)\s+fill:", source, re.M))
    # A label may be attached anywhere the id first appears -- at the start of a
    # line, on the right of an arrow, or after `subgraph` -- so the search is not
    # anchored. `GATE{"..."}` and `--> HOLD["..."]` both count.
    unlabelled = sorted(
        sid for sid in styled
        if not re.search(rf"\b{re.escape(sid)}\s*[\[({{]", source)
    )
    return {
        "styled_groups": sorted(styled),
        "styled_without_a_text_label": unlabelled,
        "greyscale_safe": not unlabelled,
    }


def build(kind: str, spec: Path, head: re.Pattern[str], out: Path,
          config: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    out.mkdir(parents=True, exist_ok=True)
    (out / "source").mkdir(exist_ok=True)
    cfg = out / "source" / "mermaid-config.json"
    cfg.write_text(json.dumps(config, indent=2), encoding="utf-8")

    text = spec.read_text(encoding="utf-8")
    produced: list[dict[str, Any]] = []

    for number, caption, body in section_bodies(text, head):
        stem = f"{prefix}{number:02d}"
        blocks = MERMAID.findall(body)
        record: dict[str, Any] = {
            "figure": number, "stem": stem, "caption": caption,
            "specification": spec.relative_to(ROOT).as_posix(),
        }

        if blocks:
            src = out / "source" / f"{stem}.mmd"
            src.write_text(blocks[0].strip() + "\n", encoding="utf-8")
            record["source"] = src.relative_to(ROOT).as_posix()
            record["source_kind"] = "mermaid"
            record["source_sha256"] = sha(src)
            record.update(greyscale_safety(blocks[0]))
            render(src, out / f"{stem}.svg", cfg)
            record["svg_size_px"] = pin_svg_size(out / f"{stem}.svg")
            render(src, out / f"{stem}.pdf", cfg)
            # An SVG px is 1/96 inch, so rendering at 300/96 puts the raster at
            # 300 dpi against the vector's own physical size. The metadata is
            # then stamped from the two sizes that actually exist on disk rather
            # than from the scale that was requested.
            png, want = out / f"{stem}.png", max(round(record["svg_size_px"][0]), 1)
            scale = RASTER_DPI / 96.0
            for _ in range(3):
                render(src, png, cfg, scale=scale, width=want)
                got = stamp_dpi(out / f"{stem}.svg", png)
                if got >= RASTER_DPI:
                    break
                # Rounding the viewport to whole pixels, and the renderer's
                # relayout inside it, both cost a little resolution. Rather than
                # publish a number just under the one promised, correct the
                # scale by the measured shortfall and render again.
                scale *= RASTER_DPI / got * 1.002
            record["png_dpi"] = got
        else:
            table = parse_table(body)
            if not table:
                record["skipped"] = "no mermaid block and no table in this section"
                produced.append(record)
                continue
            src = out / "source" / f"{stem}.json"
            src.write_text(json.dumps({"title": caption, "rows": table}, indent=2),
                           encoding="utf-8")
            record["source"] = src.relative_to(ROOT).as_posix()
            record["source_kind"] = "table"
            record["source_sha256"] = sha(src)
            record["greyscale_safe"] = True
            record["styled_without_a_text_label"] = []
            title = f"Figure {number} — {caption}"
            svg_table(table, title, out / f"{stem}.svg")
            clipped = pdf_table(table, title, out / f"{stem}.pdf")
            png_table(table, title, out / f"{stem}.png", dpi=RASTER_DPI)
            record["png_dpi"] = float(RASTER_DPI)
            record["svg_size_px"] = list(table_layout(table)[1:])
            if clipped:
                raise RuntimeError(f"{stem}: cell text overruns its column: {clipped}")

        record["assets"] = {
            p.suffix.lstrip("."): {"path": p.relative_to(ROOT).as_posix(),
                                   "bytes": p.stat().st_size, "sha256": sha(p)}
            for p in sorted(out.glob(f"{stem}.*")) if p.is_file()
        }
        produced.append(record)
        print(f"  {stem}  {record.get('source_kind', '-'):8} "
              f"{'/'.join(sorted(record['assets']))}")
    return produced


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["paper", "patent"], default=None)
    args = ap.parse_args()

    # `--only` renders one family, so the registry is updated rather than
    # replaced. Rewriting it wholesale would silently drop the other family's
    # entries and leave a registry that describes half the assets on disk.
    registry: dict[str, Any] = (
        json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.is_file() else {})
    registry |= {
        "schema": "tavonel.figure-registry.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "renderer": "@mermaid-js/mermaid-cli@11.16.0 via npx; table figures by "
                    "tools/release/render_figures.py",
        "note": (
            "Specifications are the source of truth. These assets are rendered from "
            "them and carry no content the specification does not."
        ),
    }

    if args.only in (None, "paper"):
        print("paper figures:")
        registry["paper"] = build("paper", PAPER_SPEC, FIG_HEAD, PAPER_OUT,
                                  PAPER_CONFIG, "FIG")
    if args.only in (None, "patent"):
        print("patent drawings:")
        registry["patent"] = build("patent", PATENT_SPEC, DRAW_HEAD, PATENT_OUT,
                                   PATENT_CONFIG, "SHEET")

    unsafe = [f["stem"] for group in ("paper", "patent")
              for f in registry.get(group, []) if f.get("styled_without_a_text_label")]
    registry["greyscale_unsafe_figures"] = unsafe
    registry["paper_figure_count"] = len(registry.get("paper", []))
    registry["patent_sheet_count"] = len(registry.get("patent", []))

    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"paper figures:  {registry.get('paper_figure_count')}")
    print(f"patent sheets:  {registry.get('patent_sheet_count')}")
    print(f"greyscale-unsafe: {unsafe or 'none'}")
    print(f"wrote {REGISTRY.relative_to(ROOT).as_posix()}")
    return 2 if unsafe else 0


if __name__ == "__main__":
    sys.exit(main())
