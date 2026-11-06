"""HTML -> plain text, keeping the offsets of tables and inline-XBRL facts.

The typed-extraction gold is read from the filing's own ``ix:nonFraction``
tags, so the text the model sees and the offset of the tagged number in it
must come from one pass. Hidden ``ix:header`` content is not text; its
``xbrli:context`` periods are collected instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Final

__all__ = ["Fact", "Parsed", "XbrlContext", "fact_value", "html_to_text", "squash", "tidy"]

BLOCK_TAGS: Final = frozenset(
    {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "pre"}
)
CELL_TAGS: Final = frozenset({"td", "th"})
SKIP_TAGS: Final = frozenset({"script", "style", "ix:header", "head", "title"})
NUMERIC_FORMATS: Final = frozenset(
    {"ixt:num-dot-decimal", "ixt:numdotdecimal", "ixt:fixed-zero", "ixt-sec:numwordsen", ""}
)


@dataclass(frozen=True, slots=True)
class XbrlContext:
    context_id: str
    start: str | None
    end: str | None
    instant: str | None
    dimensional: bool


@dataclass(frozen=True, slots=True)
class Fact:
    name: str
    context_ref: str
    unit_ref: str
    scale: int
    sign: str
    fmt: str
    displayed: str
    offset: int


@dataclass
class Parsed:
    text: str
    tables: list[tuple[int, int]] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    contexts: dict[str, XbrlContext] = field(default_factory=dict)


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.length = 0
        self.skip = 0
        self.tables: list[tuple[int, int]] = []
        self.open_tables: list[int] = []
        self.facts: list[Fact] = []
        self.open_facts: list[tuple[dict[str, str], int, list[str]]] = []
        self.contexts: dict[str, XbrlContext] = {}
        self.ctx: dict[str, object] | None = None
        self.ctx_field: str | None = None
        self.pre = 0
        self.cell = 0

    def _break(self, tag: str) -> str:
        # Inside a table cell a <p> or <div> is layout, not a new line of text.
        return "\n" if tag in {"tr", "table"} or not self.cell else " "

    def _emit(self, value: str) -> None:
        if self.skip:
            return
        self.parts.append(value)
        self.length += len(value)
        for _attrs, _start, chunks in self.open_facts:
            chunks.append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "xbrli:context":
            self.ctx = {"id": values.get("id", ""), "dimensional": False}
        elif self.ctx is not None and tag in {
            "xbrli:startdate",
            "xbrli:enddate",
            "xbrli:instant",
        }:
            self.ctx_field = tag.split(":")[1]
        elif self.ctx is not None and tag == "xbrli:segment":
            self.ctx["dimensional"] = True
        if tag in SKIP_TAGS:
            self.skip += 1
            return
        if tag == "pre":
            self.pre += 1
        if tag in BLOCK_TAGS:
            self._emit(self._break(tag))
        elif tag in CELL_TAGS:
            self.cell += 1
            self._emit(" | ")
        if tag == "table" and not self.skip:
            self.open_tables.append(self.length)
        if tag == "ix:nonfraction" and not self.skip:
            self.open_facts.append((values, self.length, []))

    def handle_endtag(self, tag: str) -> None:
        if tag == "xbrli:context" and self.ctx is not None:
            context_id = str(self.ctx["id"])
            self.contexts[context_id] = XbrlContext(
                context_id=context_id,
                start=_opt(self.ctx.get("startdate")),
                end=_opt(self.ctx.get("enddate")),
                instant=_opt(self.ctx.get("instant")),
                dimensional=bool(self.ctx["dimensional"]),
            )
            self.ctx = None
        if tag in {"xbrli:startdate", "xbrli:enddate", "xbrli:instant"}:
            self.ctx_field = None
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        if tag == "pre":
            self.pre = max(0, self.pre - 1)
        if tag == "ix:nonfraction" and self.open_facts and not self.skip:
            values, start, chunks = self.open_facts.pop()
            self.facts.append(
                Fact(
                    name=values.get("name", ""),
                    context_ref=values.get("contextref", ""),
                    unit_ref=values.get("unitref", ""),
                    scale=int(values.get("scale", "0") or 0),
                    sign=values.get("sign", ""),
                    fmt=values.get("format", "").lower(),
                    displayed="".join(chunks).strip(),
                    offset=start,
                )
            )
        if tag == "table" and self.open_tables and not self.skip:
            self.tables.append((self.open_tables.pop(), self.length))
        if tag in CELL_TAGS:
            self.cell = max(0, self.cell - 1)
        if tag in BLOCK_TAGS:
            self._emit(self._break(tag))

    def handle_data(self, data: str) -> None:
        if self.ctx is not None and self.ctx_field is not None:
            self.ctx[self.ctx_field] = data.strip()
        data = data.replace("\xa0", " ")
        if not self.pre:
            # HTML whitespace is insignificant outside <pre>; same-length swap keeps offsets.
            data = data.replace("\r", " ").replace("\n", " ")
        self._emit(data)


def _opt(value: object) -> str | None:
    return str(value) if value else None


def html_to_text(html: str) -> Parsed:
    parser = _Parser()
    parser.feed(html)
    parser.close()
    raw = "".join(parser.parts)
    # Collapse whitespace without moving offsets: same-length substitution only.
    text = re.sub(r"[ \t\r\f\v]", " ", raw)
    return Parsed(text=text, tables=parser.tables, facts=parser.facts, contexts=parser.contexts)


def fact_value(fact: Fact) -> Decimal | None:
    """The tagged value in base units, or ``None`` when it cannot be read exactly."""

    if fact.fmt not in NUMERIC_FORMATS:
        return None
    shown = fact.displayed.replace(",", "").replace("$", "").strip()
    if fact.fmt == "ixt:fixed-zero" or shown in {"-", "\u2014", "\u2013"}:
        number = Decimal(0)
    else:
        try:
            number = Decimal(shown)
        except InvalidOperation:
            return None
    value = number.scaleb(fact.scale)
    return -value if fact.sign == "-" else value


def tidy(text: str) -> str:
    """Prompt-ready text: no empty rows, no runs of blank lines or spaces.

    Empty cells are kept: dropping them would shift a value into the wrong
    period column, which is exactly the error the typed tasks measure.
    """

    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if line.strip("| "):
            lines.append(line)
        elif lines and lines[-1]:
            lines.append("")
    return "\n".join(lines).strip()


def squash(text: str) -> str:
    """Whitespace-insensitive form used for evidence-quote checks."""

    return re.sub(r"\s+", " ", text).strip()
