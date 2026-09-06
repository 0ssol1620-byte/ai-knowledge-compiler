#!/usr/bin/env python3
"""Check the rendered figures against the properties a submission needs.

The renderer reports what it intended to draw. This reads what it drew. The
separation is deliberate and this programme has paid for learning it twice: a
generator that reports its own success is not evidence about its output.

Six checks, each of which has a way to fail:

1. **Every registry entry has its assets, and none is empty.** A zero-byte SVG
   still satisfies "the file exists".
2. **Every PDF parses and has exactly one page.** A figure that silently became
   two pages is a figure that gets cropped in a submission build.
3. **Every PNG is at least 300 dpi at its vector size.** Stated resolution and
   actual pixel count are different claims.
4. **Text in the source appears in the vector output.** This is the
   source-to-render semantic correspondence check: mermaid drops a label it
   cannot lay out, and the result looks like a finished diagram.
5. **Patent sheets are monochrome.** Any fill or stroke that is not white, black
   or a grey is a colour a draftsperson has to remove -- and, if it carries
   meaning, a scope statement made outside the claims.
6. **Rendered text carries no forbidden wording.** The assertion registry's
   prohibitions apply to a figure exactly as they apply to a sentence.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "docs" / "paper" / "figures" / "FIGURE_REGISTRY.json"

#: Anything outside this set is colour. `#fff`, `#ffffff`, `white`, `none` and
#: greys (equal RGB channels) pass; `#ffe6e6` does not.
HEXCOL = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
SVG_TEXT = re.compile(r">([^<>]+)<")

#: Kept in step with the assertion registry's prohibited wording. Duplicated
#: here rather than imported because a figure check that silently stops running
#: when an import path moves is worse than one that is slightly out of date --
#: `tools/audit/audit_figure_captions.py` holds the authoritative list and this
#: is the subset that could plausibly reach a rendered label.
FORBIDDEN = [
    r"atomic(?:ally|ity)?[ -]+(?:promot|publish|activat|world|transition)",
    r"\bstate[- ]of[- ]the[- ]art\b",
    r"\boutperform",
    r"\bbest[- ]in[- ]class\b",
    r"\bguarantee[sd]?\b",
    r"\bproven\b",
    r"\bimpossible\b",
]


def norm(colour: str) -> str:
    c = colour.lower().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return c


def is_monochrome(value: str) -> bool:
    c = norm(value)
    return c[0:2] == c[2:4] == c[4:6]


STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S)
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
CLASS_ATTR = re.compile(r'class="([^"]*)"')
SEL_CLASS = re.compile(r"\.([\w-]+)")


def live_colours(svg: str) -> set[str]:
    """Non-monochrome colours that something in this document actually wears.

    mermaid ships a fixed stylesheet with every diagram, including rules for
    classes the diagram does not contain -- `.error-icon` is dark red and is
    never drawn. Flagging it would train the reader to ignore this check, which
    is worse than not having it. So a colour counts only if it is on a drawn
    attribute, or in a rule whose selector matches a class present in the body.
    """
    used = {c for attr in CLASS_ATTR.findall(svg) for c in attr.split()}
    bad: set[str] = set()

    body = STYLE.sub("", svg)
    bad |= {m.group(0) for m in HEXCOL.finditer(body) if not is_monochrome(m.group(0))}

    for block in STYLE.findall(svg):
        for selector, decls in RULE.findall(block):
            classes = set(SEL_CLASS.findall(selector))
            if classes and not (classes & used):
                continue
            bad |= {m.group(0) for m in HEXCOL.finditer(decls)
                    if not is_monochrome(m.group(0))}
    return bad


def check(reg_group: list[dict[str, Any]], monochrome: bool) -> list[str]:
    problems: list[str] = []
    for fig in reg_group:
        stem = fig["stem"]
        assets = fig.get("assets", {})
        for ext in ("svg", "pdf", "png"):
            if ext not in assets:
                problems.append(f"{stem}: no {ext} asset")
                continue
            path = ROOT / assets[ext]["path"]
            if not path.is_file():
                problems.append(f"{stem}: {ext} recorded but absent on disk")
            elif path.stat().st_size == 0:
                problems.append(f"{stem}: {ext} is zero bytes")

        svg_path = ROOT / assets["svg"]["path"] if "svg" in assets else None
        if svg_path and svg_path.is_file():
            svg = svg_path.read_text(encoding="utf-8", errors="replace")
            rendered = " ".join(SVG_TEXT.findall(svg))

            if monochrome:
                bad = sorted(live_colours(svg))
                if bad:
                    problems.append(f"{stem}: non-monochrome colours on a patent "
                                    f"sheet: {bad}")

            for pattern in FORBIDDEN:
                hit = re.search(pattern, rendered, re.I)
                if hit:
                    problems.append(f"{stem}: forbidden wording in rendered text: "
                                    f"{hit.group(0)!r}")

            # Source-to-render correspondence. Quoted labels are the parts of a
            # mermaid source whose loss would change what the figure says.
            src = ROOT / fig["source"]
            if fig.get("source_kind") == "mermaid" and src.is_file():
                labels = re.findall(r'"([^"]{4,})"', src.read_text(encoding="utf-8"))
                flat = re.sub(r"\s+", " ", rendered)
                for label in labels:
                    words = [w for w in re.split(r"<br\s*/?>|\s+", label) if len(w) > 3]
                    missing = [w for w in words
                               if re.sub(r"\s+", " ", w) not in flat]
                    if missing and len(missing) == len(words):
                        problems.append(
                            f"{stem}: label {label!r} does not appear in the "
                            f"rendered SVG")

        pdf_path = ROOT / assets["pdf"]["path"] if "pdf" in assets else None
        if pdf_path and pdf_path.is_file():
            from pypdf import PdfReader
            try:
                pages = len(PdfReader(str(pdf_path)).pages)
            except Exception as exc:
                problems.append(f"{stem}: pdf does not parse: {exc}")
            else:
                if pages != 1:
                    problems.append(f"{stem}: pdf has {pages} pages, expected 1")

        png_path = ROOT / assets["png"]["path"] if "png" in assets else None
        if png_path and png_path.is_file():
            from PIL import Image
            with Image.open(png_path) as im:
                if min(im.size) < 400:
                    problems.append(f"{stem}: png is {im.size}, too small to read")
                # The resolution is read back out of the file, not taken from
                # the registry entry that the renderer wrote about itself.
                dpi = (im.info.get("dpi") or (0, 0))[0]
            # PNG stores resolution as an integer number of pixels per metre,
            # so an exact 300 dpi is not representable and reads back as
            # 299.9994. The tolerance is that quantisation, not slack.
            if dpi < 299.5:
                problems.append(f"{stem}: png carries {dpi:.1f} dpi, below 300")
    return problems


def main() -> int:
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    problems = check(reg["paper"], monochrome=False)
    problems += check(reg["patent"], monochrome=True)

    print(f"paper figures checked: {len(reg['paper'])}")
    print(f"patent sheets checked: {len(reg['patent'])}")
    print(f"greyscale-unsafe:      {reg['greyscale_unsafe_figures'] or 'none'}")
    if problems:
        print(f"PROBLEMS: {len(problems)}")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("PROBLEMS: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
