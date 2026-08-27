"""Turn acquired bytes into the canonical document of protocol section 3.

Runs once, ahead of both build paths, and writes its output to disk. The
selective compiler and the independent oracle then read those files. What the
two sides share is therefore a hashed data artifact, not shared executable
logic inside either build, which is what protocol section 8.4 requires.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

SPACE = re.compile(r"\s+")
ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
FRONT_MATTER = re.compile(r"^---\s*$")
MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MD_EMPH = re.compile(r"(\*\*|\*|__|_|`)")
SHORTCODE = re.compile(r"\{\{[<%].*?[>%]\}\}", re.DOTALL)
HTML_TAG = re.compile(r"<[^>]+>")
SEC_ITEM = re.compile(r"^item\s+\d+[a-z]?\s*[.:]?", re.IGNORECASE)
SEC_PART = re.compile(r"^part\s+[ivx]+\s*[.:]?", re.IGNORECASE)

MIN_TEXT_CHARS = 120
EXCLUDED_HEADINGS = frozenset(
    {"references", "external links", "see also", "further reading", "notes"}
)


def normalise(value: str) -> str:
    value = html.unescape(value)
    return SPACE.sub(" ", value).strip()


def sha_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Section:
    path: tuple[str, ...]
    heading: str
    text: str


class SecHtmlReader(HTMLParser):
    """Flatten an EDGAR primary document into headings and body text.

    EDGAR filings rarely use ``h1``-``h6``. Their structure is carried by the
    ``Item N.`` and ``Part N`` captions that the forms themselves mandate, so
    those are treated as headings when a block element contains one and little
    else. That rule is a property of the form, not of any particular filing.
    """

    SKIP = {"script", "style", "head", "title"}
    BLOCK = {
        "p",
        "div",
        "tr",
        "li",
        "br",
        "table",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "td",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str | None, str]] = []
        self._buffer: list[str] = []
        self._skip_depth = 0
        self._heading_level: int | None = None

    def _flush(self) -> None:
        text = normalise("".join(self._buffer))
        self._buffer = []
        if not text:
            self._heading_level = None
            return
        level = self._heading_level
        if level is None and len(text) <= 120:
            if SEC_PART.match(text):
                level = 1
            elif SEC_ITEM.match(text):
                level = 2
        self.blocks.append((str(level) if level else None, text))
        self._heading_level = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self._skip_depth += 1
            return
        if tag in self.BLOCK:
            self._flush()
        if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
            self._heading_level = int(tag[1])

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in self.BLOCK:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._buffer.append(data)

    def close(self) -> None:  # noqa: D102
        super().close()
        self._flush()


def sections_from_html(payload: bytes) -> list[Section]:
    reader = SecHtmlReader()
    reader.feed(payload.decode("utf-8", errors="replace"))
    reader.close()
    return assemble(reader.blocks)


def sections_from_markdown(payload: bytes) -> list[Section]:
    text = payload.decode("utf-8", errors="replace")
    text = SHORTCODE.sub(" ", text)
    blocks: list[tuple[str | None, str]] = []
    body: list[str] = []
    in_fence = False
    in_front_matter = False
    for index, line in enumerate(text.splitlines()):
        if FRONT_MATTER.match(line) and (index == 0 or in_front_matter):
            in_front_matter = not in_front_matter
            continue
        if in_front_matter:
            continue
        if FENCE.match(line):
            in_fence = not in_fence
            body.append(line)
            continue
        match = None if in_fence else ATX.match(line)
        if match is None:
            body.append(line)
            continue
        joined = clean_markdown("\n".join(body))
        if joined:
            blocks.append((None, joined))
        body = []
        blocks.append((str(len(match.group(1))), clean_markdown(match.group(2))))
    joined = clean_markdown("\n".join(body))
    if joined:
        blocks.append((None, joined))
    return assemble(blocks)


def clean_markdown(value: str) -> str:
    value = MD_LINK.sub(r"\1", value)
    value = HTML_TAG.sub(" ", value)
    value = MD_EMPH.sub("", value)
    return normalise(value)


def assemble(blocks: list[tuple[str | None, str]]) -> list[Section]:
    """Fold a flat heading/body stream into a heading-path section list."""
    stack: list[tuple[int, str]] = []
    sections: list[Section] = []
    heading = "lead"
    level = 0
    body: list[str] = []

    def flush() -> None:
        text = normalise(" ".join(body))
        if len(text) < MIN_TEXT_CHARS:
            return
        if heading.casefold() in EXCLUDED_HEADINGS:
            return
        path = tuple(name for _, name in stack) or (heading,)
        sections.append(Section(path=path, heading=heading, text=text))

    for raw_level, text in blocks:
        if raw_level is None:
            body.append(text)
            continue
        flush()
        body = []
        level = int(raw_level)
        heading = text or "untitled"
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading))
    flush()
    return sections


def canonical_document(
    *,
    source_family: str,
    source_id: str,
    version_id: str,
    payload: bytes,
    source_digest: str,
    known_at: str | None,
    valid_from: str | None,
    licence: str,
) -> dict[str, Any]:
    reader = sections_from_html if source_family == "sec_edgar" else sections_from_markdown
    sections = reader(payload)

    seen: dict[tuple[str, ...], int] = {}
    units: list[dict[str, Any]] = []
    for ordinal, section in enumerate(sections):
        count = seen.get(section.path, 0)
        seen[section.path] = count + 1
        explicit = list(section.path)
        if count:
            explicit[-1] = explicit[-1] + "#" + str(count)
        units.append(
            {
                "explicit_path": explicit,
                "heading": section.heading,
                "ordinal": ordinal,
                "text": section.text,
                "text_sha256": sha_text(section.text),
            }
        )

    return {
        "schema": "tavonel.v2.canonical_document.v1",
        "source_family": source_family,
        "source_id": source_id,
        "version_id": version_id,
        "version_time": {"valid_from": valid_from, "known_at": known_at},
        "source_digest": source_digest,
        "license": licence,
        "units": units,
        "structure": {
            "order": ["/".join(unit["explicit_path"]) for unit in units],
            "block_count": len(units),
        },
    }
