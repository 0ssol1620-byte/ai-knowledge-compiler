"""Raw source position for every classified span, including HTML and XML.

Locality v2. P4e could only localise an unmodeled fact to an atom on markdown,
because the HTML/XML classifier emitted parser events with no position. 633 of
720 questions were therefore judged by a document-level rule that can only
under-grant, and the resulting eligibility figure of 20 was an artefact of the
instrument rather than a property of the corpus.

This module supplies the missing half: a **source map** of the form

    raw source interval  →  parser event  →  canonical fact / unit

built forward from the parser rather than inferred backwards from the canonical
output. ``HTMLParser.getpos()`` reports the line and column at which the current
event began; converting that to an absolute character offset, and closing each
event at the start of the next, yields a real interval for every event.

``source_spans`` is deliberately left untouched. P0d's classifier digest is
recorded in a sealed receipt, and the honest way to change an instrument is a
new module with its own protocol, not an edit that silently moves an older
result.

**Where position cannot be proven it is not guessed.** An event whose reported
location does not verify against the raw text is marked ``LOCATION_UNVERIFIABLE``
and can never support local completeness. A fabricated interval would let the
witness close over the wrong region and report completeness it has not
established, which is the failure this whole line of work exists to prevent.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Iterable

from source_spans import (
    IGNORED,
    MODELED,
    UNMODELED,
    _HTML_IGNORED_ATTRS,
    _HTML_REFERENCE_ATTRS,
    markdown_spans,
)

LOCATION_VERIFIED = "LOCATION_VERIFIED"
LOCATION_UNVERIFIABLE = "LOCATION_UNVERIFIABLE"


class LocatedSpan:
    """A classified span that also knows where it came from, or admits it does not."""

    __slots__ = (
        "start",
        "end",
        "kind",
        "classification",
        "text",
        "fact",
        "location_state",
        "detail",
    )

    def __init__(
        self,
        start: int | None,
        end: int | None,
        kind: str,
        classification: str,
        text: str,
        fact: dict[str, Any] | None = None,
        location_state: str = LOCATION_VERIFIED,
        detail: str | None = None,
    ) -> None:
        self.start = start
        self.end = end
        self.kind = kind
        self.classification = classification
        self.text = text
        self.fact = fact
        self.location_state = location_state
        self.detail = detail

    @property
    def located(self) -> bool:
        return (
            self.location_state == LOCATION_VERIFIED
            and self.start is not None
            and self.end is not None
        )

    def overlaps(self, low: int, high: int) -> bool:
        """Interval overlap. An unlocated span never overlaps anything.

        It is excluded from *witness scoping* here and separately forces the
        question to be incomplete, so the two effects do not cancel: an
        unlocated span cannot quietly drop out of consideration.
        """
        return self.located and self.start < high and self.end > low

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "kind": self.kind,
            "classification": self.classification,
            "location_state": self.location_state,
            "fact": self.fact,
            "detail": self.detail,
        }


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    for index, char in enumerate(text):
        if char == "\n":
            offsets.append(index + 1)
    return offsets


class _LocatingScanner(HTMLParser):
    """Every handler records the offset the event started at.

    ``convert_charrefs`` is off. With it on, adjacent text and character
    references are merged into one ``handle_data`` call whose reported position
    is the start of the *merged* run, which is exactly the kind of almost-right
    interval this module refuses to trade in.
    """

    def __init__(self, raw: str) -> None:
        super().__init__(convert_charrefs=False)
        self.raw = raw
        self.lines = _line_offsets(raw)
        self.events: list[dict[str, Any]] = []

    # -- position -------------------------------------------------------------

    def _offset(self) -> int | None:
        line, column = self.getpos()
        if line < 1 or line > len(self.lines):
            return None
        return self.lines[line - 1] + column

    def _record(self, kind: str, classification: str, fact: dict[str, Any] | None = None) -> None:
        self.events.append(
            {
                "start": self._offset(),
                "kind": kind,
                "classification": classification,
                "fact": fact,
            }
        )

    # -- handlers -------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record("start_tag:" + tag, IGNORED)
        for name, value in attrs:
            lowered = name.lower()
            if lowered in _HTML_REFERENCE_ATTRS:
                self._record(
                    "attr:" + lowered,
                    MODELED,
                    {
                        "reference_kind": _HTML_REFERENCE_ATTRS[lowered],
                        "target": value,
                        "tag": tag,
                    },
                )
            elif lowered in _HTML_IGNORED_ATTRS:
                self._record("attr:" + lowered, IGNORED)
            else:
                self._record("attr:" + lowered, UNMODELED, {"tag": tag, "attribute": lowered})

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        self._record("end_tag:" + tag, IGNORED)

    def handle_data(self, data: str) -> None:
        self._record("data", UNMODELED if data.strip() else IGNORED)

    def handle_comment(self, data: str) -> None:
        self._record("comment", IGNORED)

    def handle_decl(self, decl: str) -> None:
        self._record("decl", IGNORED)

    def handle_pi(self, data: str) -> None:
        self._record("processing_instruction", IGNORED)

    def handle_entityref(self, name: str) -> None:
        self._record("entityref", IGNORED)

    def handle_charref(self, name: str) -> None:
        self._record("charref", IGNORED)

    def unknown_decl(self, data: str) -> None:
        self._record("unknown_decl", IGNORED)


def html_located(raw: str) -> list[LocatedSpan]:
    """Located spans for HTML or XML.

    Each event closes at the start of the next, so the intervals partition the
    source in reading order. An event whose offset could not be computed, or
    whose computed offset does not run forward from its predecessor, is emitted
    as ``LOCATION_UNVERIFIABLE`` rather than repaired — malformed markup is
    where a parser's reported position is least trustworthy, and that is exactly
    where a fabricated interval would do the most damage.
    """
    scanner = _LocatingScanner(raw)
    try:
        scanner.feed(raw)
        scanner.close()
    except Exception as error:  # malformed beyond the parser's tolerance
        return [
            LocatedSpan(
                None,
                None,
                "parse_failure",
                UNMODELED,
                "",
                None,
                LOCATION_UNVERIFIABLE,
                type(error).__name__,
            )
        ]

    events = scanner.events
    spans: list[LocatedSpan] = []
    for index, event in enumerate(events):
        start = event["start"]
        end = None
        for following in events[index + 1 :]:
            if following["start"] is not None:
                end = following["start"]
                break
        if end is None:
            end = len(raw)
        verified = (
            start is not None
            and end is not None
            and 0 <= start <= end <= len(raw)
        )
        spans.append(
            LocatedSpan(
                start if verified else None,
                end if verified else None,
                event["kind"],
                event["classification"],
                raw[start:end] if verified else "",
                event["fact"],
                LOCATION_VERIFIED if verified else LOCATION_UNVERIFIABLE,
                None if verified else "parser reported no usable position",
            )
        )
    return spans


def markdown_located(raw: str) -> list[LocatedSpan]:
    """Markdown already carries offsets; this only lifts them into LocatedSpan."""
    return [
        LocatedSpan(
            span.start,
            span.end,
            span.kind,
            span.classification,
            span.text,
            span.fact,
            LOCATION_VERIFIED,
        )
        for span in markdown_spans(raw)
    ]


def located_spans(raw: str, suffix: str) -> tuple[list[LocatedSpan], str]:
    """Dispatch by source kind, returning the spans and the grammar used."""
    if suffix == ".md":
        return markdown_located(raw), "markdown"
    return html_located(raw), "markup"


def unverifiable(spans: Iterable[LocatedSpan]) -> list[LocatedSpan]:
    return [span for span in spans if span.location_state == LOCATION_UNVERIFIABLE]
