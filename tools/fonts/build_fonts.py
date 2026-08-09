"""Build the TAVONEL web font payloads from Wanted Sans Variable.

DESIGN_MASTER_V3 §7 with the amendments in design-system/tavonel/decision.md:

  A-01  budgets are /en <= 60 KB, /ko marketing first view <= 180 KB,
        /ko product UI first view <= 250 KB. The masterplan's single <= 90 KB
        is unreachable in Korean.
  A-02  the variable axis stays on Latin. Korean syllables cost roughly twice
        as many bytes per glyph in a variable font (150-200 B vs 70-100 B), so
        Korean ships as static instances at two weights.
  A-03  next/font cannot express unicode-range, so Korean is plain @font-face
        written by this script and imported only by the /ko segment.

Upstream: https://github.com/wanteddev/wanted-sans  (SIL OFL 1.1)

Usage:
    uv run --extra dev python tools/fonts/build_fonts.py --source <WantedSansVariable.ttf>

The source TTF is not vendored: it is 4.6 MB and only the outputs are shipped.
Fetch it from the npm package `wanted-sans` or the GitHub release, both v1.0.3.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "apps" / "web"
OUT_DIR = WEB_ROOT / "public" / "fonts"

# Latin, digits, punctuation, currency, arrows, and the typographic characters
# §7.5 requires (curly quotes, the ellipsis character, non-breaking space).
LATIN_UNICODES = (
    "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,"
    "U+0304,U+0308,U+0329,U+2000-206F,U+2074,U+20A0-20BF,U+2122,U+2191,"
    "U+2193,U+2192,U+2190,U+2212,U+2215,U+FEFF,U+FFFD"
)

# OpenType features kept in the Latin subset. Standard typesetting only: `kern`
# and `liga` for ordinary text, `tnum` for §7.5 tabular figures, `frac`/`zero`
# for the numeric surfaces.
#
# The stylistic and character-variant sets are deliberately dropped. They are
# not referenced by any stylesheet (see the note in foundations.css about what
# ss03 does to lowercase a in this family), so shipping them is dead weight —
# and keeping them out means a future `font-feature-settings` typo cannot
# silently swap glyphs.
LATIN_LAYOUT_FEATURES = "kern,liga,clig,calt,ccmp,mark,mkmk,tnum,frac,zero"

# A-02: two static Korean weights, matching --w-body and --w-strong.
KOREAN_WEIGHTS = (400, 600)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=pathlib.Path,
        required=True,
        help="WantedSansVariable.ttf from wanted-sans v1.0.3",
    )
    parser.add_argument(
        "--korean-text",
        type=pathlib.Path,
        default=None,
        help=(
            "File whose characters define the Korean subset. Defaults to every "
            "Korean string found under apps/web/src, which is the build-time "
            "subset §7 asks for instead of the shipped 85-chunk split."
        ),
    )
    return parser.parse_args()


def korean_characters(explicit: pathlib.Path | None) -> set[str]:
    """Collect the Hangul actually used by the app."""
    if explicit is not None:
        return {ch for ch in explicit.read_text(encoding="utf-8") if _is_korean(ch)}

    found: set[str] = set()
    for path in (WEB_ROOT / "src").rglob("*"):
        if path.suffix not in {".ts", ".tsx", ".json", ".md", ".css"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found.update(ch for ch in text if _is_korean(ch))
    return found


def _is_korean(ch: str) -> bool:
    code = ord(ch)
    return (
        0xAC00 <= code <= 0xD7A3  # syllables
        or 0x1100 <= code <= 0x11FF  # jamo
        or 0x3130 <= code <= 0x318F  # compatibility jamo
    )


def build_latin(source: pathlib.Path) -> pathlib.Path:
    """Variable Latin subset — one file, the whole weight axis."""
    target = OUT_DIR / "wanted-sans-latin-var.woff2"
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = LATIN_LAYOUT_FEATURES.split(",")
    options.desubroutinize = False
    options.hinting = True
    options.retain_gids = False
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.notdef_outline = True
    options.recalc_bounds = True

    font = subset.load_font(str(source), options)
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=subset.parse_unicodes(LATIN_UNICODES))
    subsetter.subset(font)
    subset.save_font(font, str(target), options)
    font.close()
    return target


def build_korean(source: pathlib.Path, characters: set[str]) -> list[pathlib.Path]:
    """Static instances at 400 and 600, subset to the syllables in use."""
    if not characters:
        return []

    written: list[pathlib.Path] = []
    unicodes = sorted(ord(ch) for ch in characters)

    for weight in KOREAN_WEIGHTS:
        # updateFontNames is off on purpose: Wanted Sans ships a STAT table
        # without name records for every axis value, so fontTools raises while
        # rebuilding the subfamily name. The browser resolves the face through
        # the CSS font-family declared in korean.css, not the internal name.
        instance = instantiateVariableFont(
            TTFont(str(source)), {"wght": weight}, inplace=False, updateFontNames=False
        )
        staged = OUT_DIR / f".wanted-sans-ko-{weight}.ttf"
        instance.save(str(staged))
        instance.close()

        target = OUT_DIR / f"wanted-sans-ko-{weight}.woff2"
        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["kern", "liga", "ccmp", "mark", "mkmk"]
        options.hinting = True
        options.name_IDs = ["*"]
        options.name_legacy = True

        font = subset.load_font(str(staged), options)
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(unicodes=unicodes)
        subsetter.subset(font)
        subset.save_font(font, str(target), options)
        font.close()
        staged.unlink()
        written.append(target)

    _write_korean_css(unicodes)
    return written


def _write_korean_css(unicodes: list[int]) -> None:
    """A-03: Korean is plain @font-face, imported only by the /ko segment."""
    ranges = _unicode_ranges(unicodes)
    blocks = "\n\n".join(
        f"""@font-face {{
  font-family: "Wanted Sans KO";
  font-style: normal;
  font-weight: {weight};
  font-display: swap;
  src: url("/fonts/wanted-sans-ko-{weight}.woff2") format("woff2");
  unicode-range: {ranges};
}}"""
        for weight in KOREAN_WEIGHTS
    )

    target = WEB_ROOT / "src" / "styles" / "korean.css"
    target.write_text(
        "/*\n"
        " * GENERATED by tools/fonts/build_fonts.py — do not edit by hand.\n"
        " *\n"
        " * Korean is written as plain @font-face because next/font cannot emit\n"
        " * unicode-range (vercel/next.js#47309), and it declares two static\n"
        " * weights rather than a variable axis because Korean syllables cost\n"
        " * roughly twice the bytes in a variable font (decision.md A-02, A-03).\n"
        " *\n"
        " * Import this from the /ko layout segment only. Importing it from the\n"
        " * root layout would make English visitors carry the Korean payload.\n"
        " */\n\n" + blocks + "\n",
        encoding="utf-8",
    )


def _unicode_ranges(codepoints: list[int]) -> str:
    """Collapse a sorted codepoint list into CSS unicode-range syntax."""
    if not codepoints:
        return "U+0"
    parts: list[str] = []
    start = previous = codepoints[0]
    for code in codepoints[1:]:
        if code == previous + 1:
            previous = code
            continue
        parts.append(_format_range(start, previous))
        start = previous = code
    parts.append(_format_range(start, previous))
    return ", ".join(parts)


def _format_range(start: int, end: int) -> str:
    if start == end:
        return f"U+{start:04x}"
    return f"U+{start:04x}-{end:04x}"


def main() -> int:
    args = parse_args()
    if not args.source.is_file():
        print(f"source font not found: {args.source}", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    latin = build_latin(args.source)
    characters = korean_characters(args.korean_text)
    korean = build_korean(args.source, characters)

    report = {
        "source": str(args.source),
        "latin": {"path": str(latin.relative_to(WEB_ROOT)), "bytes": latin.stat().st_size},
        "korean": [
            {"path": str(path.relative_to(WEB_ROOT)), "bytes": path.stat().st_size}
            for path in korean
        ],
        "koreanCharacters": len(characters),
        "budgets": {
            "en": 60 * 1024,
            "koMarketingFirstView": 180 * 1024,
            "koProductFirstView": 250 * 1024,
        },
    }
    (OUT_DIR / "build-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))

    if report["latin"]["bytes"] > report["budgets"]["en"]:
        print(
            f"FAIL: Latin subset is {report['latin']['bytes']} B, over the 60 KB /en budget.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
