"""Markup normaliser v1: what a candidate wrote, made readable by the frozen reader (5H-11).

The frozen reader (``critical_fields``, reader v1) reads the first token after a field's
anchor and refuses a token glued to markup, so ``<td>1,234</td>``, ``<fcel>1,234`` or
``1,234<x_0.74>`` read nothing although the value is on the page. This module turns markup
into a delimiter, a newline or a space; digits, signs, currency symbols and words are never
added, removed or reordered. Only the patterns below are touched, each bounded and linear;
anything else is left as it is and counted in ``residual``. An unknown provider raises.

Profiles: ``html`` (table cells and lines, numeric and named character references ending in
``;``), ``otsl`` (cell and line tags), ``nemotron`` (position and class tokens, LaTeX wrappers
and escapes everywhere; ``&`` becomes a cell boundary only inside ``\\begin{tabular}`` ...
``\\end{tabular}``, so "Research & development" keeps its ampersand). Last, for all
profiles: U+00A0 becomes a space, and on a line with ``|`` a cell holding only ``$ € £ ¥ (``
belongs to the nearest non-empty cell after it and a cell holding only ``)`` or ``%`` to the
nearest non-empty cell before it, mirroring how the gold builder joins symbol-only cells to
their number across empty cells (``benchmark/local_public/sec_align.py``). Only boundaries and
whitespace are removed for that; two cells that hold values stay apart.

Layout is not structure: in ``html`` a cell end and the next cell start, with only whitespace
between them, are one boundary; inside a tabular span a line break is a space (rows end at
``\\\\``), and ``&`` after an even run of backslashes is a boundary (``\\\\&`` ends a row, then a
cell). Wrappers are removed to a fixed point, at most ``TEX_PASSES`` passes; deeper nesting is
left as it is and counted in ``residual``.
"""

from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path

MODULE_SHA256 = "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

PROFILES = {
    "ovis_ocr2": "html",
    "ovis_ocr3": "html",
    "mineru": "html",
    "mineru_vlm": "html",
    "paddleocr_vl_1_6": "html",
    "xiaomi_ocr_0": "otsl",
    "nemotron_parse_3_5": "nemotron",
}

CELL = " | "

_HTML_CELL = re.compile(
    r"(?:</t[dh]\b[^<>]{0,200}>\s{0,200})?<t[dh]\b[^<>]{0,200}>|</t[dh]\b[^<>]{0,200}>",
    re.IGNORECASE,
)
_HTML_LINE = re.compile(
    r"</?(?:tr|table|thead|tbody|tfoot|p|div)\b[^<>]{0,200}>|<br\s{0,20}/?>", re.IGNORECASE
)
_ENTITY = re.compile(r"&(?:#\d{1,7}|#x[0-9A-Fa-f]{1,6}|[A-Za-z]{2,8});")

_OTSL_CELL = re.compile(r"<(?:fcel|ecel|lcel|ucel|xcel|ched|rhed|srow)>")

_POSITION = re.compile(r"<[xy]_[0-9.]{1,12}>")
_CLASS = re.compile(r"<class_[A-Za-z-]{1,40}>")
_TEX_WRAP = re.compile(r"\\(?:thead|textbf|textit|text)\{([^{}]{0,400})\}")
_TEX_MULTI = re.compile(r"\\multi(?:column|row)\{[^{}]{0,40}\}\{[^{}]{0,40}\}\{([^{}]{0,400})\}")
_BEGIN = "\\begin{tabular}"
_END = "\\end{tabular}"
_COLSPEC = re.compile(r"\{[^{}]{0,200}\}")
_TEX_AMP = re.compile(r"(?<!\\)((?:\\\\){0,50})&")  # after an even run of backslashes
TEX_PASSES = 8

_OPEN_CELL = re.compile(r"[$€£¥(]{1,3}")
_CLOSE_CELL = re.compile(r"[)%]{1,2}")
_RESIDUAL = re.compile(r"<[A-Za-z/][^<>]{0,40}>|\\[A-Za-z]+")


def _html(text: str) -> str:
    text = _HTML_CELL.sub(CELL, text)
    text = _HTML_LINE.sub("\n", text)
    return _ENTITY.sub(lambda m: html.unescape(m.group(0)), text)


def _otsl(text: str) -> str:
    return _OTSL_CELL.sub(CELL, text).replace("<nl>", "\n")


def _tabular(body: str) -> str:
    """Inside one tabular span: unescaped ``&`` is a cell boundary, ``\\\\`` and ``\\hline``
    end a line."""
    body = _TEX_AMP.sub(lambda m: m.group(1) + CELL, body.replace("\n", " "))
    return body.replace("\\\\", "\n").replace("\\hline", "\n")


def _nemotron(text: str) -> str:
    text = _CLASS.sub("\n", _POSITION.sub(" ", text))
    for _ in range(TEX_PASSES):  # nested wrappers, innermost first, to a fixed point
        unwrapped = _TEX_MULTI.sub(r"\1", _TEX_WRAP.sub(r"\1", text))
        if unwrapped == text:
            break
        text = unwrapped
    parts: list[str] = []
    at = 0
    while (begin := text.find(_BEGIN, at)) >= 0:
        end = text.find(_END, begin + len(_BEGIN))
        if end < 0:  # an unclosed span is not a table: left as it is, counted as residual
            break
        inner = text[begin + len(_BEGIN) : end]
        spec = _COLSPEC.match(inner)
        if spec is not None:
            inner = inner[spec.end() :]
        parts += [text[at:begin], "\n", _tabular(inner), "\n"]
        at = end + len(_END)
    text = "".join(parts) + text[at:]
    return text.replace("\\&", "&").replace("\\$", "$").replace("\\%", "%")


_STEPS = {"html": _html, "otsl": _otsl, "nemotron": _nemotron}


def _compact(cell: str) -> str:
    return "".join(cell.split())


def _join_symbol_cells(line: str) -> str:
    cells = line.split("|")
    out = [cells[0]]
    for cell in cells[1:]:
        if _CLOSE_CELL.fullmatch(_compact(cell)):
            while len(out) > 1 and not _compact(out[-1]):  # to the nearest non-empty cell
                out.pop()
            out[-1] = out[-1].rstrip() + " " + cell.lstrip()
        elif _OPEN_CELL.fullmatch(_compact(out[-1])):  # absorbs the empty cells after it too
            out[-1] = out[-1].rstrip() + " " + cell.lstrip()
        else:
            out.append(cell)
    return "|".join(out)


def profile_of(provider: str) -> str:
    if provider not in PROFILES:
        raise ValueError(f"no normaliser profile for provider {provider!r}")
    return PROFILES[provider]


def normalise(provider: str, text: str) -> tuple[str, int]:
    """(normalised text, residual): residual counts the tags and LaTeX commands left."""
    text = _STEPS[profile_of(provider)](text).replace("\u00a0", " ")
    text = "\n".join(_join_symbol_cells(x) if "|" in x else x for x in text.split("\n"))
    return text, len(_RESIDUAL.findall(text))
