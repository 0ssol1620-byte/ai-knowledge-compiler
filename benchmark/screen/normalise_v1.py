"""Markup normaliser v1: what a candidate wrote, made readable by the frozen reader (5H-11).

The frozen reader (``critical_fields``, reader v1) reads the first token after a field's
anchor and refuses a token glued to markup, so ``<td>1,234</td>``, ``<fcel>1,234`` or
``1,234<x_0.74>`` read nothing although the value is on the page. This module turns markup
into a delimiter, a newline or a space; digits, signs, currency symbols and words are never
added, removed or reordered. Only the patterns below are touched, each bounded and linear;
anything else is left as it is and counted in ``residual``. An unknown provider raises.
``normalise`` as a whole is linear in its input: the symbol join copies each character a
bounded number of times and never re-scans a cell it is growing (measured by a test).

Profiles: ``html`` (table cells and lines, numeric and named character references ending in
``;``), ``otsl`` (cell and line tags), ``nemotron`` (position and class tokens, LaTeX wrappers
and escapes everywhere; ``&`` becomes a cell boundary only inside ``\\begin{tabular}`` ...
``\\end{tabular}``, so "Research & development" keeps its ampersand). Last, for all
profiles: U+00A0 becomes a space, and on a line with ``|`` a cell holding only ``$ € £ ¥ (``
belongs to the nearest non-empty cell after it and a cell holding only ``)`` or ``%`` to the
nearest non-empty cell before it, mirroring how the gold builder joins symbol-only cells to
their number across empty cells (``benchmark/local_public/sec_align.py``). Only boundaries and
whitespace are removed for that; two cells that hold values stay apart.

A cell holding only ``-`` or U+2212 is not joined to the number after it (lead decision D): in
a model's table that cell is far more often an empty-value placeholder in another column than a
detached sign, and joining would invent a negative number. Known consequence: where the source
prints a detached minus sign in its own cell, gold is negative and a faithful transcription
reads positive, for every candidate alike. ``dash_cell_before_number`` finds such pages in the
normalised text (no gold) so that S0 can count them.

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
from itertools import pairwise
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
_HEAD = 4  # one more than the longest symbol cell: a cell's first 4 non-blank chars decide
_DASH_CELL = ("-", "\u2212")
_NUMBER_CELL = re.compile(r"[$€£¥(]{0,3}\d[\d,.]{0,40}[)%]{0,2}")
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


class _Cell:
    """An output cell of the symbol join, built so that no input character is copied twice.

    Its text is ``"".join(body) + tail``: ``body`` never ends in whitespace and ``tail`` is
    whitespace only. ``head`` holds the first ``_HEAD`` non-blank characters ("" = empty), all
    the open/close decision needs; the accumulated text is never scanned again.
    """

    __slots__ = ("body", "head", "tail")

    def __init__(self, cell: str, head: str) -> None:
        core = cell.rstrip()
        self.body, self.tail, self.head = [core], cell[len(core) :], head

    def join(self, cell: str, head: str) -> None:
        """``text = text.rstrip() + " " + cell.lstrip()``, without copying ``text``."""
        rest = cell.lstrip()
        core = rest.rstrip()
        if core:
            self.body.append(" " + core)
            self.tail = rest[len(core) :]
        else:
            self.tail = " "
        if len(self.head) < _HEAD:
            self.head = (self.head + head)[:_HEAD]

    def text(self) -> str:
        return "".join(self.body) + self.tail


def _join_symbol_cells(line: str) -> str:
    cells = line.split("|")
    out = [_Cell(cells[0], _compact(cells[0])[:_HEAD])]
    for cell in cells[1:]:
        head = _compact(cell)[:_HEAD]
        if _CLOSE_CELL.fullmatch(head):
            while len(out) > 1 and not out[-1].head:  # to the nearest non-empty cell
                out.pop()
            out[-1].join(cell, head)
        elif _OPEN_CELL.fullmatch(out[-1].head):  # absorbs the empty cells after it too
            out[-1].join(cell, head)
        else:
            out.append(_Cell(cell, head))
    return "|".join(c.text() for c in out)


def dash_cell_before_number(text: str) -> bool:
    """A cell holding only ``-`` or U+2212 is directly followed by a number cell (decision D:
    such a sign is never joined; S0 counts the pages so its effect is visible)."""
    for line in text.split("\n"):
        heads = [_compact(c)[:48] for c in line.split("|")] if "|" in line else []
        for cell, after in pairwise(heads):
            if cell in _DASH_CELL and _NUMBER_CELL.fullmatch(after):
                return True
    return False


def profile_of(provider: str) -> str:
    if provider not in PROFILES:
        raise ValueError(f"no normaliser profile for provider {provider!r}")
    return PROFILES[provider]


def normalise(provider: str, text: str) -> tuple[str, int]:
    """(normalised text, residual): residual counts the tags and LaTeX commands left."""
    text = _STEPS[profile_of(provider)](text).replace("\u00a0", " ")
    text = "\n".join(_join_symbol_cells(x) if "|" in x else x for x in text.split("\n"))
    return text, len(_RESIDUAL.findall(text))
